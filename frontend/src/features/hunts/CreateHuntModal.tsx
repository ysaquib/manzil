// Hunt creation flow (replaces the inline name field + button on the
// switcher). A five-stage stepper: Name, Household, Defaults, Appearance,
// Review — deliberately excludes any Rubric decision, which stays a separate
// workflow (docs/rubric-workflow.md) reached afterward through the existing
// CreateRubricPrompt nudge.
//
// Nothing is persisted until "Create hunt" on the final step: the hunt row,
// its settings, and the owner's appearance override are written in sequence
// from one submit, so closing the modal partway through never leaves a
// half-configured hunt behind. Household/estimate/proximity settings are only
// PATCHed when they differ from Manzil's defaults, and the appearance
// override is only written when it differs from the account default — an
// unedited step leaves the row inheriting user_profiles the same way it
// always has (DESIGN §8.2).
import {
  Button,
  Group,
  Modal,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Stepper,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { useProfile } from "../../auth/profile";
import { ApiError, apiFetch } from "../../lib/apiClient";
import type { HuntSettings } from "../../lib/contracts";
import type { components } from "../../lib/generated/api";
import { MemberColorControl } from "../collaboration/MemberColorControl";
import type { Hunt } from "./api";

type MemberPatch = components["schemas"]["MemberPatch"];
type HuntSettingsPatch = components["schemas"]["HuntSettingsPatch"];

const DEFAULTS = {
  occupants: 1,
  cats: 0,
  dogs: 0,
  cost_estimate_mode: "conservative" as const,
  proximity_mode: "driving" as const,
};

export function CreateHuntModal({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const userId = session?.user.id;
  const { data: profile } = useProfile(userId);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const [active, setActive] = useState(0);
  const [name, setName] = useState("");
  const [occupants, setOccupants] = useState<number>(DEFAULTS.occupants);
  const [cats, setCats] = useState<number>(DEFAULTS.cats);
  const [dogs, setDogs] = useState<number>(DEFAULTS.dogs);
  const [costEstimateMode, setCostEstimateMode] = useState<HuntSettings["cost_estimate_mode"]>(
    DEFAULTS.cost_estimate_mode,
  );
  const [proximityMode, setProximityMode] = useState<HuntSettings["proximity_mode"]>(
    DEFAULTS.proximity_mode,
  );
  const [displayName, setDisplayName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [seeded, setSeeded] = useState(false);
  const [creating, setCreating] = useState(false);

  // Fresh draft every time the modal opens, so a previous abandoned attempt
  // never leaks into the next one.
  useEffect(() => {
    if (!opened) return;
    setActive(0);
    setName("");
    setOccupants(DEFAULTS.occupants);
    setCats(DEFAULTS.cats);
    setDogs(DEFAULTS.dogs);
    setCostEstimateMode(DEFAULTS.cost_estimate_mode);
    setProximityMode(DEFAULTS.proximity_mode);
    setSeeded(false);
    setCreating(false);
  }, [opened]);

  // Seed appearance from the account default once it loads, without
  // clobbering an edit already in progress.
  if (opened && profile && !seeded) {
    setDisplayName(profile.default_display_name);
    setColor(profile.default_color);
    setSeeded(true);
  }

  const trimmedName = name.trim();

  const handleClose = () => {
    if (creating) return;
    onClose();
  };

  const create = async () => {
    if (!trimmedName || !userId) return;
    setCreating(true);
    try {
      const hunt = await apiFetch<Hunt>("/v1/hunts", {
        method: "POST",
        body: { name: trimmedName, domain: "rent" },
      });

      const settingsDirty =
        occupants !== DEFAULTS.occupants ||
        cats !== DEFAULTS.cats ||
        dogs !== DEFAULTS.dogs ||
        costEstimateMode !== DEFAULTS.cost_estimate_mode ||
        proximityMode !== DEFAULTS.proximity_mode;
      if (settingsDirty) {
        await apiFetch(`/v1/hunts/${hunt.id}/settings`, {
          method: "PATCH",
          body: {
            settings: { occupants, cats, dogs, cost_estimate_mode: costEstimateMode, proximity_mode: proximityMode },
          } satisfies HuntSettingsPatch,
        });
      }

      const trimmedDisplayName = displayName.trim();
      if (trimmedDisplayName && trimmedDisplayName !== profile?.default_display_name) {
        await apiFetch(`/v1/hunts/${hunt.id}/members/${userId}`, {
          method: "PATCH",
          body: { display_name: trimmedDisplayName } satisfies MemberPatch,
        });
      }
      if (color && color !== profile?.default_color) {
        await apiFetch(`/v1/hunts/${hunt.id}/members/${userId}`, {
          method: "PATCH",
          body: { color } satisfies MemberPatch,
        });
      }

      void qc.invalidateQueries({ queryKey: ["hunts"] });
      onClose();
      navigate(`/h/${hunt.id}`);
    } catch (error) {
      notifications.show({
        title: "Couldn't create hunt",
        message: error instanceof ApiError ? error.message : "Unexpected error",
        color: "red",
      });
    } finally {
      setCreating(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title="Create a new hunt"
      size="lg"
      closeOnClickOutside={!creating}
      closeOnEscape={!creating}
      withCloseButton={!creating}
    >
      <Stepper active={active} onStepClick={setActive} allowNextStepsSelect={false} size="sm">
        <Stepper.Step label="Name" description="What is it called">
          <Stack gap="md" mt="lg">
            <TextInput
              label="Hunt name"
              placeholder="e.g. Apartment Search 2026"
              description="This is what you and everyone you invite will see everywhere."
              value={name}
              onChange={(event) => setName(event.currentTarget.value)}
              onKeyDown={(event) => event.key === "Enter" && trimmedName && setActive(1)}
              maxLength={200}
              autoFocus
              data-autofocus
            />
            <Group justify="flex-end">
              <Button onClick={() => setActive(1)} disabled={!trimmedName}>
                Next
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Household" description="Who's moving in">
          <Stack gap="md" mt="lg">
            <Text size="xs" c="dimmed">
              Feeds the all-in cost estimate — pet rent and utility scaling both use these
              numbers. Change them later without losing anything.
            </Text>
            <SimpleGrid cols={{ base: 1, xs: 3 }} spacing="sm">
              <NumberInput
                label="People moving in"
                min={1}
                max={20}
                step={1}
                allowDecimal={false}
                value={occupants}
                onChange={(value) => setOccupants(typeof value === "number" ? value : occupants)}
              />
              <NumberInput
                label="Cats"
                min={0}
                max={10}
                step={1}
                allowDecimal={false}
                value={cats}
                onChange={(value) => setCats(typeof value === "number" ? value : cats)}
              />
              <NumberInput
                label="Dogs"
                min={0}
                max={10}
                step={1}
                allowDecimal={false}
                value={dogs}
                onChange={(value) => setDogs(typeof value === "number" ? value : dogs)}
              />
            </SimpleGrid>
            <Group justify="space-between">
              <Button variant="default" onClick={() => setActive(0)}>
                Back
              </Button>
              <Button onClick={() => setActive(2)}>Next</Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Defaults" description="Estimates & proximity">
          <Stack gap="md" mt="lg">
            <Text size="xs" c="dimmed">
              Manzil's defaults work for most searches. Both are one click away in Hunt Settings
              if a listing changes your mind.
            </Text>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <Select
                label="Cost estimates"
                description="Conservative uses the worst realistic month for estimated utilities."
                data={[
                  { value: "conservative", label: "Conservative (peak month)" },
                  { value: "median", label: "Median month" },
                ]}
                value={costEstimateMode}
                onChange={(value) =>
                  value && setCostEstimateMode(value as HuntSettings["cost_estimate_mode"])
                }
                allowDeselect={false}
              />
              <Select
                label="Proximity mode"
                description="Travel mode for location criteria like grocery proximity."
                data={[
                  { value: "driving", label: "Driving" },
                  { value: "walking", label: "Walking" },
                ]}
                value={proximityMode}
                onChange={(value) =>
                  value && setProximityMode(value as HuntSettings["proximity_mode"])
                }
                allowDeselect={false}
              />
            </SimpleGrid>
            <Group justify="space-between">
              <Button variant="default" onClick={() => setActive(1)}>
                Back
              </Button>
              <Button onClick={() => setActive(3)}>Next</Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Appearance" description="How you'll appear">
          <Stack gap="md" mt="lg">
            <Text size="xs" c="dimmed">
              Pre-filled from your account profile. This changes only this hunt — your account
              default stays the same.
            </Text>
            <TextInput
              label="Display name in this hunt"
              description="Shown on your comments, ratings, and the roster."
              value={displayName}
              onChange={(event) => setDisplayName(event.currentTarget.value)}
              maxLength={80}
            />
            <MemberColorControl
              value={color}
              loading={false}
              onChange={setColor}
              label="Your color in this hunt"
            />
            <Group justify="space-between">
              <Button variant="default" onClick={() => setActive(2)}>
                Back
              </Button>
              <Button onClick={() => setActive(4)}>Next</Button>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Review" description="Confirm & create">
          <Stack gap="md" mt="lg">
            <Stack gap="xs">
              <ReviewRow label="Name" value={trimmedName || "—"} />
              <ReviewRow
                label="Household"
                value={`${occupants} ${occupants === 1 ? "person" : "people"}${
                  cats ? `, ${cats} ${cats === 1 ? "cat" : "cats"}` : ""
                }${dogs ? `, ${dogs} ${dogs === 1 ? "dog" : "dogs"}` : ""}`}
              />
              <ReviewRow
                label="Cost estimates"
                value={costEstimateMode === "conservative" ? "Conservative" : "Median"}
              />
              <ReviewRow
                label="Proximity mode"
                value={proximityMode === "driving" ? "Driving" : "Walking"}
              />
              <ReviewRow label="You'll appear as" value={displayName.trim() || "—"} />
            </Stack>
            <Text size="xs" c="dimmed">
              Everything above can be changed later in Hunt Settings. Next, you can build a
              Rubric — or skip it and add your first listing.
            </Text>
            <Group justify="space-between">
              <Button variant="default" onClick={() => setActive(3)} disabled={creating}>
                Back
              </Button>
              <Button onClick={create} loading={creating} disabled={!trimmedName}>
                Create hunt
              </Button>
            </Group>
          </Stack>
        </Stepper.Step>
      </Stepper>
    </Modal>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between" gap="sm" wrap="nowrap">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={600} ta="right">
        {value}
      </Text>
    </Group>
  );
}
