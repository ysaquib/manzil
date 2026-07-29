// Hunt settings (P1-5 + P2-8 consumer; reshaped by P3-16, DESIGN §20 v3.27).
//
// Two tabs, split on the only line a person actually holds in their head:
// **Hunt** is everything about the hunt itself (name, household, scoring
// defaults, People, danger zone), **Your profile** is everything about you in
// this hunt (display name, color, role and permissions).
//
// The scoring-defaults panel batches into one save bar that names what changed;
// single-field commits — rename, a member's role — stay inline, because a save
// bar for one field is ceremony. Scoring-affecting keys rescore for free; the
// source-policy default affects future submissions only. Destructive-adjacent
// actions sit in the danger zone behind confirm modals. Role gating here is
// UX — RLS and the API are the enforcement.
import {
  Alert,
  Button,
  Center,
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
import { IconHome, IconUserCircle } from "@tabler/icons-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { SectionCard } from "../../components/SectionCard";
import {
  SettingsSaveBar,
  SettingsShell,
  type SettingsTab,
} from "../../components/SettingsShell";
import { useAuth } from "../../auth/useAuth";
import {
  useCurrentMember,
  useMembers,
  useSetMemberColor,
  useSetMemberDisplayName,
  useTransferOwnership,
} from "../collaboration/api";
import { MemberColorControl } from "../collaboration/MemberColorControl";
import { MembersSection } from "../collaboration/MembersSection";
import { RolePermissionsCard } from "../collaboration/RolePermissionsCard";
import { InvitesSection } from "../invites/InvitesSection";
import { InvitationLinksSection } from "../invites/InvitationLinksSection";
import { ApiError } from "../../lib/apiClient";
import { resolveSettings, SOURCE_POLICIES, type HuntSettings } from "../../lib/contracts";
import { useHunt, usePatchHunt, usePatchHuntSettings, type Hunt } from "./api";

const TABS: SettingsTab[] = [
  {
    value: "hunt",
    label: "Hunt",
    description: "Scoring, people, name",
    icon: <IconHome size={16} stroke={1.6} />,
  },
  {
    value: "profile",
    label: "Your profile",
    description: "Name, color, role",
    icon: <IconUserCircle size={16} stroke={1.6} />,
  },
];

/** Field → the words the save bar uses. Keyed by the settings contract (§8.2). */
const SETTING_LABEL: Record<keyof HuntSettings, string> = {
  occupants: "people moving in",
  cats: "cats",
  dogs: "dogs",
  default_source_policy: "cross-checking",
  cost_estimate_mode: "cost estimates",
  min_confidence: "extraction confidence",
  min_vision_confidence: "VISION confidence",
  generalized_vision_policy: "gallery estimates",
  proximity_mode: "proximity mode",
};

function notifyError(title: string) {
  return (error: unknown) =>
    notifications.show({
      title,
      message: error instanceof ApiError ? error.message : "Unexpected error",
      color: "red",
    });
}

function HuntPanel({ hunt, isOwner }: { hunt: Hunt; isOwner: boolean }) {
  const { session } = useAuth();
  const currentUserId = session?.user.id ?? "";
  const { data: members = [] } = useMembers(hunt.id);
  const transferOwnership = useTransferOwnership(hunt.id);
  const patchHunt = usePatchHunt(hunt.id);
  const patchSettings = usePatchHuntSettings(hunt.id);
  const navigate = useNavigate();

  const saved = resolveSettings(hunt.settings);
  const [name, setName] = useState(hunt.name);
  const [settings, setSettings] = useState<HuntSettings>(saved);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [transferTarget, setTransferTarget] = useState<string | null>(null);
  const [confirmTransfer, setConfirmTransfer] = useState(false);

  const transferOptions = members
    .filter((member) => member.user_id !== currentUserId)
    .map((member) => ({ value: member.user_id, label: member.display_name ?? "Member" }));
  const transferTargetName =
    members.find((member) => member.user_id === transferTarget)?.display_name ?? "this Member";

  const set = <K extends keyof HuntSettings>(key: K, value: HuntSettings[K]) =>
    setSettings((prev) => ({ ...prev, [key]: value }));

  const dirtyLabels = (Object.keys(SETTING_LABEL) as (keyof HuntSettings)[])
    .filter((key) => settings[key] !== saved[key])
    .map((key) => SETTING_LABEL[key]);

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
    <>
      <SectionCard title="General">
        <Group align="flex-end" gap="sm">
          <TextInput
            label="Hunt name"
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
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
      </SectionCard>

      <SectionCard title="Household" hint="Feeds all-in cost">
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            People and pets change the all-in cost estimate, so saving re-scores every listing in
            the background.
          </Text>
          <SimpleGrid cols={{ base: 1, xs: 3 }} spacing="sm">
            <NumberInput
              label="People moving in"
              min={1}
              max={20}
              step={1}
              allowDecimal={false}
              value={settings.occupants}
              onChange={(value) =>
                set("occupants", typeof value === "number" ? value : settings.occupants)
              }
            />
            <NumberInput
              label="Cats"
              min={0}
              max={10}
              step={1}
              allowDecimal={false}
              value={settings.cats}
              onChange={(value) => set("cats", typeof value === "number" ? value : settings.cats)}
            />
            <NumberInput
              label="Dogs"
              min={0}
              max={10}
              step={1}
              allowDecimal={false}
              value={settings.dogs}
              onChange={(value) => set("dogs", typeof value === "number" ? value : settings.dogs)}
            />
          </SimpleGrid>
        </Stack>
      </SectionCard>

      <SectionCard title="Scoring defaults" hint="Re-scores on save">
        <Stack gap="sm">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <Select
              label="Cost estimates"
              description="Conservative uses the worst realistic month for estimated utilities."
              data={[
                { value: "conservative", label: "Conservative (peak month)" },
                { value: "median", label: "Median month" },
              ]}
              value={settings.cost_estimate_mode}
              onChange={(value) =>
                value && set("cost_estimate_mode", value as HuntSettings["cost_estimate_mode"])
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
              value={settings.proximity_mode}
              onChange={(value) =>
                value && set("proximity_mode", value as HuntSettings["proximity_mode"])
              }
              allowDeselect={false}
            />
            <Select
              label="Minimum extraction confidence"
              description="Non-VISION Extractions below this score as unknown."
              data={[
                { value: "low", label: "Low" },
                { value: "medium", label: "Medium" },
                { value: "high", label: "High" },
              ]}
              value={settings.min_confidence}
              onChange={(value) =>
                value && set("min_confidence", value as HuntSettings["min_confidence"])
              }
              allowDeselect={false}
            />
            <Select
              label="Minimum VISION confidence"
              description="Low keeps uncertain image evidence for points and display, but it can never pass a Gate."
              data={[
                { value: "low", label: "Low (default)" },
                { value: "medium", label: "Medium" },
                { value: "high", label: "High" },
              ]}
              value={settings.min_vision_confidence}
              onChange={(value) =>
                value &&
                set("min_vision_confidence", value as HuntSettings["min_vision_confidence"])
              }
              allowDeselect={false}
            />
          </SimpleGrid>
          <Select
            label="Property-gallery visual estimates"
            description="Exact Floor Plan assessments always use the full rubric. Gallery estimates may represent a different unit."
            data={[
              { value: "full_rubric", label: "Full rubric (default) — points and Gates" },
              { value: "points_only", label: "Points only — Gates treat the estimate as unknown" },
              { value: "unknown", label: "Display only — exclude from scoring" },
            ]}
            value={settings.generalized_vision_policy}
            onChange={(value) =>
              value &&
              set("generalized_vision_policy", value as HuntSettings["generalized_vision_policy"])
            }
            allowDeselect={false}
          />
          <Select
            label="Default cross-checking"
            description="Applies to future submissions; existing listings keep their policy."
            data={SOURCE_POLICIES}
            value={settings.default_source_policy}
            onChange={(value) =>
              value && set("default_source_policy", value as HuntSettings["default_source_policy"])
            }
            allowDeselect={false}
          />
        </Stack>
      </SectionCard>

      {/* Members, email invites, and invitation links are one job — People. */}
      <SectionCard
        title="People"
        hint={`${members.length} ${members.length === 1 ? "member" : "members"}`}
      >
        <Stack gap="lg">
          <MembersSection
            huntId={hunt.id}
            members={members}
            currentUserId={currentUserId}
            isOwner={isOwner}
          />
          {isOwner && <InvitesSection huntId={hunt.id} />}
          {isOwner && <InvitationLinksSection huntId={hunt.id} />}
        </Stack>
      </SectionCard>

      <SectionCard title="Danger zone">
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
                  color="red"
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
          <Button variant="light" color="red" onClick={() => setConfirmArchive(true)}>
            Archive hunt…
          </Button>
        </Stack>
      </SectionCard>

      <SettingsSaveBar
        dirtyLabels={dirtyLabels}
        saving={patchSettings.isPending}
        onSave={saveSettings}
        onDiscard={() => setSettings(saved)}
      />

      <Modal opened={confirmArchive} onClose={() => setConfirmArchive(false)} title="Archive hunt?">
        <Stack>
          <Text size="sm">
            <Text span fw={600}>
              {hunt.name}
            </Text>{" "}
            disappears from your hunts. Listings, scores, and history are kept.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmArchive(false)}>
              Cancel
            </Button>
            <Button color="red" onClick={archive} loading={patchHunt.isPending}>
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
            becomes the Owner of{" "}
            <Text span fw={600}>
              {hunt.name}
            </Text>
            . You become a{" "}
            <Text span fw={600}>
              Curator
            </Text>{" "}
            and lose owner-only controls. This can only be undone by the new Owner.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmTransfer(false)}>
              Cancel
            </Button>
            <Button color="red" onClick={transfer} loading={transferOwnership.isPending}>
              Transfer ownership
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function YourProfilePanel({ hunt }: { hunt: Hunt }) {
  const { session } = useAuth();
  const currentUserId = session?.user.id ?? "";
  const { data: members = [] } = useMembers(hunt.id);
  const { data: currentMember } = useCurrentMember(hunt.id);
  const setColor = useSetMemberColor(hunt.id, currentUserId);
  const setDisplayName = useSetMemberDisplayName(hunt.id, currentUserId);

  const savedName = currentMember?.display_name ?? "";
  const savedColor = currentMember?.color ?? null;

  const [name, setName] = useState("");
  const [color, setColorDraft] = useState<string | null>(null);
  // Seed the editors from the loaded member row once it arrives, without
  // clobbering in-progress edits.
  const [seeded, setSeeded] = useState(false);
  if (!seeded && currentMember) {
    setName(savedName);
    setColorDraft(savedColor);
    setSeeded(true);
  }

  const owner = members.find((member) => member.role === "owner");
  const saving = setDisplayName.isPending || setColor.isPending;

  const dirtyLabels: string[] = [];
  if (seeded && name !== savedName) dirtyLabels.push("display name");
  if (seeded && color !== savedColor) dirtyLabels.push("color");

  const save = () => {
    if (name !== savedName) {
      setDisplayName.mutate(name.trim(), {
        onError: notifyError("Couldn't save display name"),
      });
    }
    // The palette control always yields a token; the null case is only the
    // pre-seed state, which cannot be dirty.
    if (color !== null && color !== savedColor) {
      setColor.mutate(color, { onError: notifyError("Couldn't save color") });
    }
  };

  return (
    <>
      <SectionCard title="How you appear here" hint={hunt.name}>
        <Stack gap="md">
          <TextInput
            label="Display name in this hunt"
            description="Shown on your comments, ratings, and the roster."
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            maxLength={80}
          />
          <MemberColorControl
            value={color}
            loading={saving}
            onChange={setColorDraft}
            label="Your color in this hunt"
          />
        </Stack>
      </SectionCard>

      {/* Rendered only once the membership is known: defaulting to `member`
          while it loads would flash the wrong permission set at an Owner, which
          is precisely the confusion this card exists to end. */}
      {currentMember && (
        <RolePermissionsCard
          role={currentMember.role}
          ownerName={
            owner && owner.user_id !== currentUserId ? (owner.display_name ?? undefined) : undefined
          }
        />
      )}

      <SettingsSaveBar
        dirtyLabels={dirtyLabels}
        saving={saving}
        onSave={save}
        onDiscard={() => {
          setName(savedName);
          setColorDraft(savedColor);
        }}
      />
    </>
  );
}

export function HuntSettingsPage() {
  const { huntId = "", tab } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();
  const { data: hunt, isLoading, error } = useHunt(huntId);
  const { data: members = [] } = useMembers(huntId);

  const active = TABS.some((candidate) => candidate.value === tab) ? tab! : "hunt";
  const isOwner = hunt?.owner_id === (session?.user.id ?? "");

  return (
    <Stack gap="lg">
      <PageHeader
        title="Hunt settings"
        description={
          hunt
            ? `${hunt.name} · ${members.length} ${members.length === 1 ? "member" : "members"}`
            : undefined
        }
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
      {hunt && (
        <SettingsShell
          tabs={TABS}
          active={active}
          onSelect={(value) => navigate(`/h/${huntId}/settings/${value}`)}
        >
          {active === "hunt" ? (
            <HuntPanel hunt={hunt} isOwner={isOwner} />
          ) : (
            <YourProfilePanel hunt={hunt} />
          )}
        </SettingsShell>
      )}
    </Stack>
  );
}
