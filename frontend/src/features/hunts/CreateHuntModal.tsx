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
//
// Presentation notes: navigation is one shared footer rather than a pair of
// buttons repeated per panel; the two-way settings are option cards rather
// than Selects, because each option carries a sentence of consequence that a
// closed dropdown hides; and Review is a grid of tiles that jump back to the
// step owning the value, so the last screen is a summary you can act on
// instead of a table to proof-read.
import {
  Alert,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  NumberInput,
  SimpleGrid,
  Stack,
  Stepper,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconCat,
  IconCheck,
  IconClipboardCheck,
  IconCoin,
  IconDog,
  IconPalette,
  IconPencil,
  IconRoute,
  IconSparkles,
  IconTag,
  IconUser,
  IconUsers,
} from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { useProfile } from "../../auth/profile";
import { ApiError, apiFetch } from "../../lib/apiClient";
import type { HuntSettings } from "../../lib/contracts";
import type { components } from "../../lib/generated/api";
import { MemberColorControl } from "../collaboration/MemberColorControl";
import { memberColor } from "../collaboration/memberColors";
import type { Hunt } from "./api";
import classes from "./CreateHuntModal.module.css";

type MemberPatch = components["schemas"]["MemberPatch"];
type HuntSettingsPatch = components["schemas"]["HuntSettingsPatch"];

const DEFAULTS = {
  occupants: 1,
  cats: 0,
  dogs: 0,
  cost_estimate_mode: "conservative" as const,
  proximity_mode: "driving" as const,
};

const LAST_STEP = 4;

/** What the submit is doing right now — one line per request it makes. */
type CreatePhase = "hunt" | "settings" | "appearance";
const PHASE_LABEL: Record<CreatePhase, string> = {
  hunt: "Creating the hunt…",
  settings: "Saving household and defaults…",
  appearance: "Applying how you'll appear…",
};

const COST_ESTIMATE_OPTIONS = [
  {
    value: "conservative" as const,
    label: "Conservative",
    description: "Budget for the worst realistic month — the winter peak for estimated utilities.",
  },
  {
    value: "median" as const,
    label: "Median month",
    description: "Budget for a typical month. Lower estimates, less headroom in January.",
  },
];

const PROXIMITY_OPTIONS = [
  {
    value: "driving" as const,
    label: "Driving",
    description: "Distances to groceries and other places are measured as drive time.",
  },
  {
    value: "walking" as const,
    label: "Walking",
    description: "Measured as walk time — the right call for a dense, walkable search.",
  },
];

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function describePets(cats: number, dogs: number): string {
  const parts: string[] = [];
  if (cats > 0) parts.push(plural(cats, "cat", "cats"));
  if (dogs > 0) parts.push(plural(dogs, "dog", "dogs"));
  return parts.length === 0 ? "no pets" : parts.join(" and ");
}

function describeHousehold(occupants: number, cats: number, dogs: number): string {
  return `${plural(occupants, "person", "people")} · ${describePets(cats, dogs)}`;
}

/** One panel's heading. Serif, like every other heading in the app. */
function StepHeading({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap={4}>
      <Title order={4} size="h5">
        {title}
      </Title>
      <Text size="sm" c="dimmed" lh={1.5}>
        {children}
      </Text>
    </Stack>
  );
}

function ChoiceCard({
  label,
  description,
  icon,
  selected,
  onSelect,
}: {
  label: string;
  description: string;
  icon: ReactNode;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <UnstyledButton
      role="radio"
      aria-checked={selected}
      data-selected={selected || undefined}
      className={classes.choice}
      onClick={onSelect}
    >
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <ThemeIcon
          variant={selected ? "filled" : "light"}
          color={selected ? "primary" : "gray"}
          size="md"
          radius="sm"
          mt={2}
        >
          {icon}
        </ThemeIcon>
        <Box style={{ flex: 1 }}>
          <Text size="sm" fw={600} lh={1.4}>
            {label}
          </Text>
          <Text size="xs" c="dimmed" lh={1.45}>
            {description}
          </Text>
        </Box>
        {selected && (
          <IconCheck
            size={16}
            stroke={2.5}
            style={{ flex: "none", marginTop: 4, color: "var(--mantine-primary-color-filled)" }}
          />
        )}
      </Group>
    </UnstyledButton>
  );
}

/** A Review value that jumps back to the step that owns it. */
function ReviewTile({
  label,
  icon,
  onEdit,
  children,
}: {
  label: string;
  icon: ReactNode;
  onEdit: () => void;
  children: ReactNode;
}) {
  return (
    <UnstyledButton className={classes.tile} onClick={onEdit} aria-label={`Edit ${label}`}>
      <Group gap={6} wrap="nowrap" mb={4}>
        <Box c="dimmed" style={{ display: "flex" }}>
          {icon}
        </Box>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: "0.06em" }}>
          {label}
        </Text>
        <Box style={{ flex: 1 }} />
        <IconPencil size={13} stroke={1.8} className={classes.tileEdit} />
      </Group>
      {children}
    </UnstyledButton>
  );
}

export function CreateHuntModal({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const userId = session?.user.id;
  const { data: profile, isLoading: profileLoading } = useProfile(userId);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;

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
  const [phase, setPhase] = useState<CreatePhase | null>(null);

  const creating = phase !== null;

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
    setPhase(null);
  }, [opened]);

  // Seed appearance from the account default once it loads, without
  // clobbering an edit already in progress.
  if (opened && profile && !seeded) {
    setDisplayName(profile.default_display_name);
    setColor(profile.default_color);
    setSeeded(true);
  }

  const trimmedName = name.trim();
  const trimmedDisplayName = displayName.trim();
  const canAdvance = active !== 0 || trimmedName.length > 0;

  const handleClose = () => {
    if (creating) return;
    onClose();
  };

  const create = async () => {
    if (!trimmedName || !userId) return;
    try {
      setPhase("hunt");
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
        setPhase("settings");
        await apiFetch(`/v1/hunts/${hunt.id}/settings`, {
          method: "PATCH",
          body: {
            settings: {
              occupants,
              cats,
              dogs,
              cost_estimate_mode: costEstimateMode,
              proximity_mode: proximityMode,
            },
          } satisfies HuntSettingsPatch,
        });
      }

      const nameDirty = trimmedDisplayName && trimmedDisplayName !== profile?.default_display_name;
      const colorDirty = color && color !== profile?.default_color;
      if (nameDirty || colorDirty) setPhase("appearance");
      if (nameDirty) {
        await apiFetch(`/v1/hunts/${hunt.id}/members/${userId}`, {
          method: "PATCH",
          body: { display_name: trimmedDisplayName } satisfies MemberPatch,
        });
      }
      if (colorDirty) {
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
      setPhase(null);
    }
  };

  const stepLabel = (label: string) => (isCompact ? undefined : label);

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title="Create a new hunt"
      size="lg"
      padding="lg"
      closeOnClickOutside={!creating}
      closeOnEscape={!creating}
      withCloseButton={!creating}
      styles={{ title: { fontWeight: 600 } }}
    >
      <Stepper
        active={active}
        onStepClick={setActive}
        allowNextStepsSelect={false}
        size="sm"
        iconSize={32}
      >
        <Stepper.Step label={stepLabel("Name")} icon={<IconTag size={16} stroke={1.7} />}>
          <Stack gap="lg" mt="xl">
            <StepHeading title="What should we call it?">
              This is what you and everyone you invite will see — on the switcher, in invitations,
              and in every email this hunt sends.
            </StepHeading>
            <TextInput
              label="Hunt name"
              placeholder="e.g. Apartment Search 2026"
              value={name}
              onChange={(event) => setName(event.currentTarget.value)}
              onKeyDown={(event) => event.key === "Enter" && trimmedName && setActive(1)}
              maxLength={200}
              size="md"
              autoFocus
              data-autofocus
            />
          </Stack>
        </Stepper.Step>

        <Stepper.Step label={stepLabel("Household")} icon={<IconUsers size={16} stroke={1.7} />}>
          <Stack gap="lg" mt="xl">
            <StepHeading title="Who's moving in?">
              Pet rent and utility estimates both scale with these numbers, so they feed every
              all-in cost this hunt shows you.
            </StepHeading>
            <SimpleGrid cols={{ base: 1, xs: 3 }} spacing="sm">
              <NumberInput
                label="People"
                leftSection={<IconUser size={15} stroke={1.7} />}
                min={1}
                max={20}
                step={1}
                allowDecimal={false}
                clampBehavior="strict"
                value={occupants}
                onChange={(value) => setOccupants(typeof value === "number" ? value : occupants)}
              />
              <NumberInput
                label="Cats"
                leftSection={<IconCat size={15} stroke={1.7} />}
                min={0}
                max={10}
                step={1}
                allowDecimal={false}
                clampBehavior="strict"
                value={cats}
                onChange={(value) => setCats(typeof value === "number" ? value : cats)}
              />
              <NumberInput
                label="Dogs"
                leftSection={<IconDog size={15} stroke={1.7} />}
                min={0}
                max={10}
                step={1}
                allowDecimal={false}
                clampBehavior="strict"
                value={dogs}
                onChange={(value) => setDogs(typeof value === "number" ? value : dogs)}
              />
            </SimpleGrid>
            <Group gap="xs">
              <Text size="xs" c="dimmed">
                Costs will be estimated for
              </Text>
              <Badge variant="light" color="primary" size="sm">
                {describeHousehold(occupants, cats, dogs)}
              </Badge>
            </Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step
          label={stepLabel("Defaults")}
          icon={<IconCoin size={16} stroke={1.7} />}
        >
          <Stack gap="lg" mt="xl">
            <StepHeading title="How should we estimate?">
              Manzil's defaults suit most searches, and both are one click away in Hunt settings if
              a listing changes your mind.
            </StepHeading>

            <Stack gap="xs">
              <Text size="sm" fw={500}>
                Cost estimates
              </Text>
              <Stack gap={6} role="radiogroup" aria-label="Cost estimates">
                {COST_ESTIMATE_OPTIONS.map((option) => (
                  <ChoiceCard
                    key={option.value}
                    label={option.label}
                    description={option.description}
                    icon={<IconCoin size={15} stroke={1.7} />}
                    selected={costEstimateMode === option.value}
                    onSelect={() => setCostEstimateMode(option.value)}
                  />
                ))}
              </Stack>
            </Stack>

            <Stack gap="xs">
              <Text size="sm" fw={500}>
                Proximity mode
              </Text>
              <Stack gap={6} role="radiogroup" aria-label="Proximity mode">
                {PROXIMITY_OPTIONS.map((option) => (
                  <ChoiceCard
                    key={option.value}
                    label={option.label}
                    description={option.description}
                    icon={<IconRoute size={15} stroke={1.7} />}
                    selected={proximityMode === option.value}
                    onSelect={() => setProximityMode(option.value)}
                  />
                ))}
              </Stack>
            </Stack>
          </Stack>
        </Stepper.Step>

        <Stepper.Step
          label={stepLabel("Appearance")}
          icon={<IconPalette size={16} stroke={1.7} />}
        >
          <Stack gap="lg" mt="xl">
            <StepHeading title="How you'll appear here">
              Pre-filled from your account profile. Changing either one applies to this hunt only —
              your account default stays as it is.
            </StepHeading>

            {profileLoading && !seeded ? (
              <Group gap="xs" py="lg" justify="center">
                <Loader size="sm" />
                <Text size="sm" c="dimmed">
                  Loading your profile…
                </Text>
              </Group>
            ) : (
              <>
                <TextInput
                  label="Display name"
                  description="Shown on your comments, ratings, and the member roster."
                  value={displayName}
                  onChange={(event) => setDisplayName(event.currentTarget.value)}
                  maxLength={80}
                />
                <MemberColorControl
                  value={color}
                  loading={creating}
                  onChange={setColor}
                  label="Your color"
                />
                <Group
                  gap="sm"
                  wrap="nowrap"
                  p="sm"
                  style={{
                    border: "1px solid var(--mantine-color-default-border)",
                    borderRadius: "var(--mantine-radius-md)",
                  }}
                >
                  <Box
                    className={classes.previewDot}
                    style={{ "--preview-color": memberColor(color) } as CSSProperties}
                  />
                  <Box>
                    <Text size="sm" fw={600} lh={1.3}>
                      {trimmedDisplayName || "Your name"}
                    </Text>
                    <Text size="xs" c="dimmed" lh={1.3}>
                      How you'll look on comments and ratings
                    </Text>
                  </Box>
                </Group>
              </>
            )}
          </Stack>
        </Stepper.Step>

        <Stepper.Step
          label={stepLabel("Review")}
          icon={<IconClipboardCheck size={16} stroke={1.7} />}
        >
          <Stack gap="lg" mt="xl">
            <StepHeading title="Ready to go">
              Everything here stays editable in Hunt settings. Select any card to change it now.
            </StepHeading>

            <Stack gap="sm">
              <ReviewTile label="Name" icon={<IconTag size={13} stroke={1.8} />} onEdit={() => setActive(0)}>
                <Text size="sm" fw={600}>
                  {trimmedName || "—"}
                </Text>
              </ReviewTile>

              <SimpleGrid cols={{ base: 1, xs: 2 }} spacing="sm">
                <ReviewTile
                  label="Household"
                  icon={<IconUsers size={13} stroke={1.8} />}
                  onEdit={() => setActive(1)}
                >
                  <Text size="sm" fw={600}>
                    {plural(occupants, "person", "people")}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {describePets(cats, dogs)}
                  </Text>
                </ReviewTile>

                <ReviewTile
                  label="Estimates"
                  icon={<IconCoin size={13} stroke={1.8} />}
                  onEdit={() => setActive(2)}
                >
                  <Text size="sm" fw={600}>
                    {costEstimateMode === "conservative" ? "Conservative" : "Median month"}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {proximityMode === "driving" ? "Driving" : "Walking"} proximity
                  </Text>
                </ReviewTile>
              </SimpleGrid>

              <ReviewTile
                label="You'll appear as"
                icon={<IconPalette size={13} stroke={1.8} />}
                onEdit={() => setActive(3)}
              >
                <Group gap="xs" wrap="nowrap">
                  <Box
                    className={classes.previewDot}
                    style={
                      { "--preview-color": memberColor(color), width: "1.1rem", height: "1.1rem" } as CSSProperties
                    }
                  />
                  <Text size="sm" fw={600}>
                    {trimmedDisplayName || "—"}
                  </Text>
                </Group>
              </ReviewTile>
            </Stack>

            <Alert
              variant="light"
              color="primary"
              icon={<IconSparkles size={17} stroke={1.7} />}
              p="sm"
            >
              <Text size="sm" lh={1.5}>
                Next, build a Rubric so listings can be scored — or skip it and add your first
                listing straight away.
              </Text>
            </Alert>
          </Stack>
        </Stepper.Step>
      </Stepper>

      <Divider mt="xl" mb="md" />

      <Group justify="space-between" wrap="nowrap">
        {creating ? (
          <Group gap="xs" wrap="nowrap">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              {PHASE_LABEL[phase]}
            </Text>
          </Group>
        ) : active === 0 ? (
          <Button variant="subtle" color="gray" onClick={handleClose}>
            Cancel
          </Button>
        ) : (
          <Button variant="default" onClick={() => setActive((step) => step - 1)}>
            Back
          </Button>
        )}

        {active === LAST_STEP ? (
          <Button onClick={create} loading={creating} disabled={!trimmedName}>
            Create hunt
          </Button>
        ) : (
          <Button onClick={() => setActive((step) => step + 1)} disabled={!canAdvance}>
            Next
          </Button>
        )}
      </Group>
    </Modal>
  );
}
