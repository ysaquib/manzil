// Hunt settings (P1-5 consumer, §8.2): name/archive + the 4-key settings
// form. Scoring-affecting keys (cost mode, min confidence) rescore for free;
// the source-policy default affects future submissions only. Members/roles/
// invites arrive with Phase 2. Archive is destructive-adjacent → confirm
// modal, tucked at the bottom (frontend/AGENTS.md hierarchy).
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
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
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
  const patchHunt = usePatchHunt(hunt.id);
  const patchSettings = usePatchHuntSettings(hunt.id);
  const navigate = useNavigate();

  const [name, setName] = useState(hunt.name);
  const [settings, setSettings] = useState<HuntSettings>(() => resolveSettings(hunt.settings));
  const [confirmArchive, setConfirmArchive] = useState(false);

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

      <Section title="Danger zone">
        <Stack gap="sm">
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
    </Stack>
  );
}

export function HuntSettingsPage() {
  const { huntId = "" } = useParams();
  const { data: hunt, isLoading, error } = useHunt(huntId);

  return (
    <Stack gap="lg">
      <PageHeader title="Settings" description="Hunt name, scoring defaults, and archive" />
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
