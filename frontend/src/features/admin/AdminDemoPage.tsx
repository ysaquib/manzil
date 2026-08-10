import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  List,
  Loader,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle,
  IconCheck,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { ApiError } from "../../lib/apiClient";
import {
  type DemoPreflight,
  useAdminDemoStatus,
  useDemoHuntOptions,
  useDemoPreflight,
  usePublishDemo,
  useToggleDemo,
} from "./api";

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unexpected error";
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card withBorder padding="md">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text ff="monospace" fw={700} size="lg">{value}</Text>
    </Card>
  );
}

export function AdminDemoPage() {
  const status = useAdminDemoStatus();
  // demo-guarded: useDemoPreflight — the Admin shell and backend Site Admin
  // authorization make this mutation unreachable to Demo sessions.
  const preflight = useDemoPreflight();
  const publish = usePublishDemo();
  const toggle = useToggleDemo();
  const [opened, setOpened] = useState(false);
  const [huntSearch, setHuntSearch] = useState("");
  const [huntId, setHuntId] = useState<string | null>(null);
  const [review, setReview] = useState<DemoPreflight | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [enableAfterPublish, setEnableAfterPublish] = useState(false);
  const hunts = useDemoHuntOptions(huntSearch);

  const huntOptions = useMemo(
    () =>
      (hunts.data ?? []).map((hunt) => ({
        value: hunt.hunt_id,
        label: `${hunt.name} · ${hunt.active_listings} live · ${hunt.archived_listings} archived`,
      })),
    [hunts.data],
  );
  const busy = status.data?.publication?.state === "queued" ||
    status.data?.publication?.state === "building";

  const openSelection = (current = false, enableOnSuccess = false) => {
    setHuntId(current ? (status.data?.hunt_id ?? null) : null);
    setReview(null);
    setConfirmation("");
    setEnableAfterPublish(enableOnSuccess);
    setOpened(true);
    if (current && status.data?.hunt_id) {
      preflight.mutate(status.data.hunt_id, {
        onSuccess: setReview,
        onError: (error) => notifications.show({
          color: "red", title: "Couldn't review Demo Hunt", message: message(error),
        }),
      });
    }
  };

  const reviewHunt = () => {
    if (!huntId) return;
    preflight.mutate(huntId, {
      onSuccess: (result) => {
        setReview(result);
        setConfirmation("");
      },
      onError: (error) => notifications.show({
        color: "red", title: "Couldn't review Demo Hunt", message: message(error),
      }),
    });
  };

  const queuePublication = () => {
    if (!review) return;
    publish.mutate(
      {
        confirmationId: review.confirmation_id,
        confirmationText: confirmation,
        enableOnSuccess: enableAfterPublish,
      },
      {
        onSuccess: () => {
          setOpened(false);
          setReview(null);
          notifications.show({
            color: "green",
            title: "Demo publication queued",
            message: "The current public release stays intact until the new one is complete.",
          });
        },
        onError: (error) => notifications.show({
          color: "red", title: "Couldn't publish Demo Hunt", message: message(error),
        }),
      },
    );
  };

  const setEnabled = (enabled: boolean) => toggle.mutate(enabled, {
    onSuccess: () => notifications.show({
      color: enabled ? "green" : "gray",
      title: enabled ? "Demo Mode enabled" : "Demo Mode disabled",
      message: enabled
        ? "Visitors can now enter the selected Demo Hunt."
        : "Existing Demo sessions were revoked; the Hunt and release were retained.",
    }),
    onError: (error) => notifications.show({
      color: "red", title: "Couldn't change Demo Mode", message: message(error),
    }),
  });

  if (status.isPending) return <Loader size="sm" />;
  if (status.isError || !status.data) {
    return <Alert color="red" title="Couldn't load Demo Mode">{message(status.error)}</Alert>;
  }
  const data = status.data;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Stack gap={4}>
          <Title order={2}>Demo Mode</Title>
          <Text c="dimmed" maw={720}>
            Publish one of your Hunts as the public, read-only Demo Hunt. Live Hunt data stays
            current; archived replays and map stills change only when you publish updates.
          </Text>
        </Stack>
        <Badge
          size="lg"
          color={data.available ? "sage" : data.enabled ? "red" : "gray"}
          variant="light"
        >
          {data.available ? "Public" : data.enabled ? "Blocked" : "Private"}
        </Badge>
      </Group>

      <Card withBorder shadow="sm" padding="lg">
        <Stack gap="md">
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <Stack gap={2}>
              <Title order={4}>{data.hunt_name ?? "No Demo Hunt selected"}</Title>
              <Text size="sm" c="dimmed">
                {data.published_at
                  ? `Last published ${new Date(data.published_at).toLocaleString()}`
                  : "Select a Hunt to create the first release."}
              </Text>
            </Stack>
            <Group>
              {data.enabled ? (
                <Button
                  color="red"
                  variant="light"
                  leftSection={<IconPlayerPause size={16} />}
                  loading={toggle.isPending}
                  onClick={() => setEnabled(false)}
                >
                  Turn off Demo Mode
                </Button>
              ) : data.release_id && !data.stale && data.owned_by_caller ? (
                <Button
                  leftSection={<IconPlayerPlay size={16} />}
                  loading={toggle.isPending}
                  onClick={() => setEnabled(true)}
                >
                  Enable Demo Mode
                </Button>
              ) : null}
            </Group>
          </Group>

          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <Stat label="Live Listings" value={data.active_count} />
            <Stat label="Replay Captures" value={data.replay_count} />
            <Stat label="Mapped Properties" value={data.mapped_count} />
            <Stat label="Derived assets" value={data.stale ? "Updates available" : data.release_id ? "Current" : "Not published"} />
          </SimpleGrid>

          {busy && (
            <Alert color="ochre" icon={<Loader size="sm" />} title="Publishing Demo release">
              Captures and both map themes are being generated. The previous release remains public.
            </Alert>
          )}
          {data.enabled && !data.available && (
            <Alert
              color="red"
              icon={<IconAlertTriangle size={18} />}
              title="Demo access is blocked"
            >
              {data.blockers.length > 0 ? (
                <List size="sm">
                  {data.blockers.map((item) => <List.Item key={item}>{item}</List.Item>)}
                </List>
              ) : (
                "The configured release no longer passes the public availability check."
              )}
            </Alert>
          )}
          {data.freshness_error && (
            <Alert color="red" title="Couldn't verify publication freshness">
              {data.freshness_error}
            </Alert>
          )}
          {data.publication && ["failed", "superseded"].includes(data.publication.state) && (
            <Alert color="red" icon={<IconAlertTriangle size={18} />} title="Publication did not promote">
              {data.publication.error ?? "The Hunt changed during publication. Review and retry."}
            </Alert>
          )}
          {data.stale && !busy && (
            <Alert color="ochre" title="Replay or map inputs changed">
              Visitors see live Hunt changes immediately, but new archived replays and map coverage
              wait for an atomic publication.
            </Alert>
          )}
          {data.warnings.map((warning) => <Alert key={warning} color="gray">{warning}</Alert>)}

          <Group justify="flex-end">
            {data.hunt_id && data.owned_by_caller && (
              <Button
                variant="default"
                leftSection={<IconRefresh size={16} />}
                disabled={busy}
                onClick={() => openSelection(true, false)}
              >
                Publish updates
              </Button>
            )}
            <Button
              disabled={busy}
              onClick={() => openSelection(false, !data.release_id)}
            >
              {data.hunt_id ? "Change Demo Hunt" : "Select Demo Hunt"}
            </Button>
          </Group>
        </Stack>
      </Card>

      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title={review ? "Confirm public Demo release" : "Select your Demo Hunt"}
        size="lg"
      >
        {!review ? (
          <Stack>
            <Select
              label="Hunt"
              description="Only Hunts you own are eligible. Type to filter your Hunts."
              searchable
              data={huntOptions}
              value={huntId}
              searchValue={huntSearch}
              onSearchChange={setHuntSearch}
              onChange={setHuntId}
              nothingFoundMessage={hunts.isPending ? "Loading…" : "No owned Hunts found"}
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setOpened(false)}>Cancel</Button>
              <Button disabled={!huntId} loading={preflight.isPending} onClick={reviewHunt}>
                Review public content
              </Button>
            </Group>
          </Stack>
        ) : (
          <Stack>
            <Alert color="ochre" icon={<IconAlertTriangle size={18} />} title="This Hunt becomes public">
              A Demo visitor receives Curator-level read access. The database still refuses every write.
            </Alert>
            <SimpleGrid cols={{ base: 2, sm: 4 }}>
              <Stat label="Live Listings" value={review.active_listings} />
              <Stat label="Archived replays" value={review.replay_ready} />
              <Stat label="Mapped Properties" value={review.mapped_properties} />
              <Stat label="Members" value={review.human_content.members ?? 0} />
            </SimpleGrid>
            <Card withBorder padding="md">
              <Text fw={600} mb="xs">Visitor-readable collaboration content</Text>
              <SimpleGrid cols={{ base: 2, sm: 3 }}>
                {Object.entries(review.human_content)
                  .filter(([key]) => key !== "members")
                  .map(([key, value]) => (
                    <Group key={key} gap="xs">
                      <ThemeIcon size="sm" variant="light" color="gray"><IconCheck size={12} /></ThemeIcon>
                      <Text size="sm">{key.replaceAll("_", " ")}: {value}</Text>
                    </Group>
                  ))}
              </SimpleGrid>
            </Card>
            {review.blockers.length > 0 && (
              <Alert color="red" title="Resolve these blockers before publishing">
                <List size="sm">{review.blockers.map((item) => <List.Item key={item}>{item}</List.Item>)}</List>
              </Alert>
            )}
            {review.warnings.length > 0 && (
              <Alert color="ochre" title="Review carefully">
                <List size="sm">{review.warnings.map((item) => <List.Item key={item}>{item}</List.Item>)}</List>
              </Alert>
            )}
            <TextInput
              label={`Type “${review.hunt_name}” to confirm`}
              value={confirmation}
              onChange={(event) => setConfirmation(event.currentTarget.value)}
            />
            <Group justify="space-between">
              <Button variant="default" onClick={() => setReview(null)}>Back</Button>
              <Button
                disabled={review.blockers.length > 0 || confirmation !== review.hunt_name}
                loading={publish.isPending}
                onClick={queuePublication}
              >
                {enableAfterPublish ? "Publish and enable" : "Publish release"}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
