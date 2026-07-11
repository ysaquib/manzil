// Hunt settings (P1-5 + P2-8 consumer, §8.2 / §13.1): name/archive + the
// 4-key settings form, plus the Phase 2 collaboration surface — Members &
// roles, Invites, your profile (display name + color), and ownership transfer.
// Scoring-affecting keys (cost mode, min confidence) rescore for free; the
// source-policy default affects future submissions only. Destructive-adjacent
// actions (archive, transfer) sit in the danger zone behind confirm modals
// (frontend/AGENTS.md hierarchy). Role gating here is UX — RLS + the API are
// the enforcement.
import {
  Alert,
  Button,
  Center,
  ColorInput,
  Group,
  Loader,
  Modal,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../auth/useAuth";
import {
  useMembers,
  useSetMemberColor,
  useSetMemberDisplayName,
  useTransferOwnership,
} from "../collaboration/api";
import { MembersSection } from "../collaboration/MembersSection";
import { MEMBER_COLOR_TOKENS, memberColor } from "../collaboration/memberColors";
import { InvitesSection } from "../invites/InvitesSection";
import { Section } from "../../components/Section";
import { ApiError } from "../../lib/apiClient";
import { resolveSettings, SOURCE_POLICIES, type HuntSettings } from "../../lib/contracts";
import { semantic } from "../../theme";
import { useHunt, usePatchHunt, usePatchHuntSettings, type Hunt } from "./api";

function notifyError(title: string) {
  return (error: unknown) =>
    notifications.show({
      title,
      message: error instanceof ApiError ? error.message : "Unexpected error",
      color: "red",
    });
}

function SettingsForm({ hunt }: { hunt: Hunt }) {
  const { session } = useAuth();
  const currentUserId = session?.user.id ?? "";
  const isOwner = hunt.owner_id === currentUserId;
  const { data: members = [] } = useMembers(hunt.id);
  const currentMember = members.find((member) => member.user_id === currentUserId);
  const setColor = useSetMemberColor(hunt.id, currentUserId);
  const setDisplayName = useSetMemberDisplayName(hunt.id, currentUserId);
  const transferOwnership = useTransferOwnership(hunt.id);
  const patchHunt = usePatchHunt(hunt.id);
  const patchSettings = usePatchHuntSettings(hunt.id);
  const navigate = useNavigate();

  const [name, setName] = useState(hunt.name);
  const [settings, setSettings] = useState<HuntSettings>(() => resolveSettings(hunt.settings));
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [customColor, setCustomColor] = useState("#5C5CAA");
  const [displayName, setDisplayNameInput] = useState("");
  const [transferTarget, setTransferTarget] = useState<string | null>(null);
  const [confirmTransfer, setConfirmTransfer] = useState(false);

  // Seed the display-name editor from the loaded member row once it arrives,
  // without clobbering in-progress edits.
  const savedDisplayName = currentMember?.display_name ?? "";
  const [seededName, setSeededName] = useState(false);
  if (!seededName && currentMember) {
    setDisplayNameInput(savedDisplayName);
    setSeededName(true);
  }

  const transferOptions = members
    .filter((member) => member.user_id !== currentUserId)
    .map((member) => ({ value: member.user_id, label: member.display_name ?? "Member" }));
  const transferTargetName =
    members.find((member) => member.user_id === transferTarget)?.display_name ?? "this Member";

  const set = <K extends keyof HuntSettings>(key: K, value: HuntSettings[K]) =>
    setSettings((prev) => ({ ...prev, [key]: value }));

  const saveName = () =>
    patchHunt.mutate(
      { name },
      {
        onSuccess: () => notifications.show({ message: "Hunt renamed", color: "green" }),
        onError: notifyError("Couldn't rename hunt"),
      },
    );

  const saveSettings = () =>
    patchSettings.mutate(
      { settings: { ...settings } },
      {
        onSuccess: () =>
          notifications.show({
            message: "Settings saved — scoring-related changes re-score in the background.",
            color: "green",
          }),
        onError: notifyError("Couldn't save settings"),
      },
    );

  const archive = () =>
    patchHunt.mutate(
      { archived: true },
      {
        onSuccess: () => navigate("/"),
        onError: notifyError("Couldn't archive hunt"),
      },
    );

  const saveDisplayName = () =>
    setDisplayName.mutate(displayName.trim(), {
      onSuccess: () => notifications.show({ message: "Display name saved", color: "green" }),
      onError: notifyError("Couldn't save display name"),
    });

  const transfer = () => {
    if (!transferTarget) return;
    transferOwnership.mutate(transferTarget, {
      onSuccess: () => {
        setConfirmTransfer(false);
        setTransferTarget(null);
        notifications.show({ message: "Ownership transferred", color: "green" });
      },
      onError: notifyError("Couldn't transfer ownership"),
    });
  };

  return (
    <Stack gap="xl" maw={520}>
      <Section title="General">
        <Group align="flex-end" gap="sm">
          <TextInput
            label="Hunt name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button
            variant="default"
            onClick={saveName}
            disabled={!name.trim() || name === hunt.name || patchHunt.isPending}
          >
            Rename
          </Button>
        </Group>
      </Section>

      <Section title="Household">
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Pets feed the all-in cost estimate — changing them re-scores in the background.
          </Text>
          <SimpleGrid cols={3} spacing="sm">
            <NumberInput
              label="People moving in"
              min={1}
              max={20}
              step={1}
              allowDecimal={false}
              value={settings.occupants}
              onChange={(v) => set("occupants", typeof v === "number" ? v : settings.occupants)}
            />
            <NumberInput
              label="Cats"
              min={0}
              max={10}
              step={1}
              allowDecimal={false}
              value={settings.cats}
              onChange={(v) => set("cats", typeof v === "number" ? v : settings.cats)}
            />
            <NumberInput
              label="Dogs"
              min={0}
              max={10}
              step={1}
              allowDecimal={false}
              value={settings.dogs}
              onChange={(v) => set("dogs", typeof v === "number" ? v : settings.dogs)}
            />
          </SimpleGrid>
        </Stack>
      </Section>

      <Section title="Scoring defaults">
        <Stack gap="sm">
          <Select
            label="Default cross-checking"
            description="Applies to future submissions; existing listings keep their policy."
            data={SOURCE_POLICIES}
            value={settings.default_source_policy}
            onChange={(v) => v && set("default_source_policy", v as HuntSettings["default_source_policy"])}
            allowDeselect={false}
          />
          <Select
            label="Cost estimates"
            description="Conservative uses the worst realistic month for estimated utilities."
            data={[
              { value: "conservative", label: "Conservative (peak month)" },
              { value: "median", label: "Median month" },
            ]}
            value={settings.cost_estimate_mode}
            onChange={(v) => v && set("cost_estimate_mode", v as HuntSettings["cost_estimate_mode"])}
            allowDeselect={false}
          />
          <Select
            label="Minimum extraction confidence"
            description="Extractions below this score as unknown — low-confidence data can't pass a gate."
            data={[
              { value: "low", label: "Low" },
              { value: "medium", label: "Medium" },
              { value: "high", label: "High" },
            ]}
            value={settings.min_confidence}
            onChange={(v) => v && set("min_confidence", v as HuntSettings["min_confidence"])}
            allowDeselect={false}
          />
          <Select
            label="Proximity mode"
            description="Travel mode for location criteria like grocery proximity."
            data={[
              { value: "driving", label: "Driving" },
              { value: "walking", label: "Walking" },
            ]}
            value={settings.proximity_mode}
            onChange={(v) => v && set("proximity_mode", v as HuntSettings["proximity_mode"])}
            allowDeselect={false}
          />
          <Group>
            <Button onClick={saveSettings} loading={patchSettings.isPending}>
              Save settings
            </Button>
          </Group>
        </Stack>
      </Section>

      <Section title="Your profile">
        <Stack gap="sm">
          <Group align="flex-end" gap="sm">
            <TextInput
              label="Display name"
              description="How teammates see you on comments, ratings, and this roster."
              value={displayName}
              onChange={(e) => setDisplayNameInput(e.currentTarget.value)}
              maxLength={80}
              style={{ flex: 1 }}
            />
            <Button
              variant="default"
              onClick={saveDisplayName}
              disabled={
                !displayName.trim() ||
                displayName.trim() === savedDisplayName ||
                setDisplayName.isPending
              }
            >
              Save
            </Button>
          </Group>
          <Select
            label="Palette color"
            data={MEMBER_COLOR_TOKENS.map((token) => ({ value: token, label: token }))}
            value={currentMember?.color && !currentMember.color.startsWith("#") ? currentMember.color : null}
            onChange={(value) => value && setColor.mutate(value)}
            renderOption={({ option }) => (
              <Group gap="xs"><span style={{ width: 10, height: 10, borderRadius: "50%", background: memberColor(option.value), display: "inline-block" }} />{option.label}</Group>
            )}
          />
          <Group align="flex-end">
            <ColorInput label="Custom color" value={customColor} onChange={setCustomColor} format="hex" style={{ flex: 1 }} />
            <Button variant="default" onClick={() => setColor.mutate(customColor)} loading={setColor.isPending}>Use custom</Button>
          </Group>
        </Stack>
      </Section>

      <MembersSection
        huntId={hunt.id}
        members={members}
        currentUserId={currentUserId}
        isOwner={isOwner}
      />

      {isOwner && <InvitesSection huntId={hunt.id} />}

      <Section title="Danger zone">
        <Stack gap="sm">
          {isOwner && (
            <Stack gap="xs">
              <Text size="xs" c="dimmed">
                Hand this hunt to another Member. You become a Curator; they take over as Owner.
              </Text>
              <Group align="flex-end" gap="sm">
                <Select
                  label="Transfer ownership to"
                  placeholder={transferOptions.length ? "Choose a Member" : "No other Members yet"}
                  data={transferOptions}
                  value={transferTarget}
                  onChange={setTransferTarget}
                  disabled={transferOptions.length === 0}
                  style={{ flex: 1 }}
                />
                <Button
                  variant="light"
                  color={semantic.danger}
                  disabled={!transferTarget}
                  onClick={() => setConfirmTransfer(true)}
                >
                  Transfer…
                </Button>
              </Group>
            </Stack>
          )}
          <Text size="xs" c="dimmed">
            Hides this hunt from the switcher; nothing is deleted.
          </Text>
          <Button variant="light" color={semantic.danger} onClick={() => setConfirmArchive(true)}>
            Archive hunt…
          </Button>
        </Stack>
      </Section>

      <Modal opened={confirmArchive} onClose={() => setConfirmArchive(false)} title="Archive hunt?">
        <Stack>
          <Text size="sm">
            <Text span fw={600}>{hunt.name}</Text> disappears from your hunts. Listings, scores,
            and history are kept.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmArchive(false)}>
              Cancel
            </Button>
            <Button color={semantic.danger} onClick={archive} loading={patchHunt.isPending}>
              Archive
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={confirmTransfer}
        onClose={() => setConfirmTransfer(false)}
        title="Transfer ownership?"
      >
        <Stack>
          <Text size="sm">
            <Text span fw={600}>
              {transferTargetName}
            </Text>{" "}
            becomes the Owner of <Text span fw={600}>{hunt.name}</Text>. You become a{" "}
            <Text span fw={600}>Curator</Text> and lose owner-only controls. This can only be undone
            by the new Owner.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmTransfer(false)}>
              Cancel
            </Button>
            <Button
              color={semantic.danger}
              onClick={transfer}
              loading={transferOwnership.isPending}
            >
              Transfer ownership
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

export function HuntSettingsPage() {
  const { huntId = "" } = useParams();
  const { data: hunt, isLoading, error } = useHunt(huntId);

  return (
    <Stack gap="lg">
      <PageHeader
        title="Settings"
        description="Members, invites, your profile, scoring defaults, and danger zone"
      />
      {isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {error && (
        <Alert color="red" title="Couldn't load hunt">
          {error.message}
        </Alert>
      )}
      {hunt && <SettingsForm hunt={hunt} />}
    </Stack>
  );
}
