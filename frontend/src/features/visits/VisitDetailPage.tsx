// One Visit (VC-2, DESIGN §9.7, §13.2).
//
// Pre-visit is a state, not a screen: a planned Visit is one whose tour has not
// started, so only the property-scoped **Before you go** section is answerable
// and *Start visit* unlocks the rest (VC-3 fills in the controls).
import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Menu,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconDotsVertical,
  IconLock,
  IconPlayerPlay,
  IconPlayerStop,
  IconRotateClockwise,
  IconTrash,
} from "@tabler/icons-react";
import dayjs from "dayjs";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { ApiError } from "../../lib/apiClient";
import { useCurrentMember, useMembers } from "../collaboration/api";
import { useDeleteVisit, usePatchVisit, useVisit, useVisitTemplate } from "./api";
import { VisitChecklist } from "./VisitChecklist";
import { VisitConfirmDialog } from "./VisitConfirmDialog";
import { VisitDefects } from "./VisitDefects";
import { VisitStatePill } from "./VisitStatePill";
import { VisitUnitChips } from "./VisitUnitChips";
import { groupIntoSections, sectionTitle, visitState } from "./visitState";

export function VisitDetailPage() {
  const { huntId = "", visitId = "" } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();
  const visitQuery = useVisit(visitId);
  const membersQuery = useMembers(huntId);
  const currentMember = useCurrentMember(huntId);
  const patchVisit = usePatchVisit(huntId);
  const deleteVisit = useDeleteVisit(huntId);
  const [cancelOpen, cancelModal] = useDisclosure(false);
  const [deleteOpen, deleteModal] = useDisclosure(false);

  const visit = visitQuery.data;
  const templateQuery = useVisitTemplate(visit?.template_version);

  if (visitQuery.isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (!visit) {
    return (
      <Stack gap="md" maw={560}>
        <Alert color="gray" title="Visit not found">
          It may have been deleted, or it belongs to a hunt you can't see.
        </Alert>
        <Button component={Link} to={`/h/${huntId}/visits`} variant="light" w="fit-content">
          Back to visits
        </Button>
      </Stack>
    );
  }

  const state = visitState(visit);
  const units = visit.visit_units ?? [];
  // Two different questions, previously conflated. **Visibility** follows
  // whether the tour ever began: cancelling a visit that had already started
  // must not hide what was recorded on it. **Editability** follows the derived
  // state — a finished or cancelled tour is a record, not a form.
  const hasStarted = visit.started_at !== null;
  const readOnly = state === "completed" || state === "cancelled";
  const sections = groupIntoSections(templateQuery.data ?? []);
  const lockedSections = sections.filter((section) => section.key !== "prep");

  // Cancel and delete narrow to the creator or the Owner (DESIGN §4.2); the API
  // and a database trigger both enforce it, so this only shapes the UI.
  const mayCancel =
    visit.created_by === session?.user.id || currentMember.data?.role === "owner";

  const creatorName =
    membersQuery.data?.find((member) => member.user_id === visit.created_by)?.display_name ??
    "a member";

  const act = (action: "start" | "end" | "reopen" | "cancel" | "reinstate", reason?: string) =>
    patchVisit.mutate({
      visitId: visit.id,
      body: { action, ...(reason ? { cancel_reason: reason } : {}) },
    });

  return (
    <Stack gap="lg" maw={760}>
      <Group gap="xs">
        <Button
          component={Link}
          to={`/h/${huntId}/visits`}
          variant="subtle"
          size="compact-sm"
          leftSection={<IconArrowLeft size={14} />}
        >
          Visits
        </Button>
      </Group>

      <Card>
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Box style={{ minWidth: 0 }}>
              <Title order={3}>{visit.property?.name ?? "Unknown property"}</Title>
              <Text size="sm" c="dimmed">
                {visit.property?.canonical_address}
              </Text>
            </Box>
            <Group gap="xs" wrap="nowrap" style={{ flex: "none" }}>
              <VisitStatePill state={state} />
              <Menu position="bottom-end">
                <Menu.Target>
                  <Button variant="subtle" color="gray" size="compact-sm" aria-label="Visit actions">
                    <IconDotsVertical size={16} />
                  </Button>
                </Menu.Target>
                <Menu.Dropdown>
                  {state === "cancelled" ? (
                    <Menu.Item
                      leftSection={<IconRotateClockwise size={14} />}
                      disabled={!mayCancel}
                      onClick={() => act("reinstate")}
                    >
                      Reinstate visit
                    </Menu.Item>
                  ) : (
                    <Menu.Item
                      leftSection={<IconAlertTriangle size={14} />}
                      disabled={!mayCancel}
                      onClick={cancelModal.open}
                    >
                      Cancel visit
                    </Menu.Item>
                  )}
                  <Menu.Item
                    color="red"
                    leftSection={<IconTrash size={14} />}
                    disabled={!mayCancel}
                    onClick={deleteModal.open}
                  >
                    Delete visit
                  </Menu.Item>
                  {!mayCancel && (
                    <Menu.Label>Only the creator or the Owner can do these</Menu.Label>
                  )}
                </Menu.Dropdown>
              </Menu>
            </Group>
          </Group>

          <VisitUnitChips units={units} />

          <Text size="xs" c="dimmed">
            Set up by {creatorName} ·{" "}
            {visit.scheduled_for
              ? `scheduled ${dayjs(visit.scheduled_for).format("ddd D MMM, h:mm A")}`
              : `created ${dayjs(visit.created_at).format("ddd D MMM")}`}
            {visit.started_at
              ? ` · started ${dayjs(visit.started_at).format("h:mm A")}`
              : ""}
            {visit.ended_at ? ` · ended ${dayjs(visit.ended_at).format("h:mm A")}` : ""}
          </Text>

          {visit.cancel_reason && (
            <Text size="sm" c="dimmed" fs="italic">
              Cancelled: {visit.cancel_reason}
            </Text>
          )}

          {patchVisit.isError && (
            <Alert color="red" title="That didn't work">
              {patchVisit.error instanceof ApiError
                ? patchVisit.error.message
                : "Something went wrong."}
            </Alert>
          )}
        </Stack>
      </Card>

      {/* Before the tour starts only the property-scoped prep section is
          answerable — the room questions cannot honestly be answered before
          anyone has seen a room (DESIGN §9.7). */}
      <VisitChecklist
        visit={visit}
        readOnly={readOnly}
        restrictTo={hasStarted ? undefined : ["prep"]}
      />

      {hasStarted && (
        <VisitDefects
          visitId={visit.id}
          units={units}
          activeUnitId={units[0]?.id ?? null}
          readOnly={readOnly}
        />
      )}

      {!hasStarted && lockedSections.length > 0 && (
        <Card>
          <Stack gap="sm">
            <Group justify="space-between">
              <Title order={5}>Unlocks when you start</Title>
              <Text size="xs" c="dimmed">
                {lockedSections.length} sections
              </Text>
            </Group>
            <Group gap={6} wrap="wrap">
              {lockedSections.map((locked) => (
                <Tooltip
                  key={locked.key}
                  label={
                    locked.hasUnitScoped && locked.hasPropertyScoped
                      ? "Mixed — some answers per unit, some once for the property"
                      : locked.hasUnitScoped
                        ? "Answered once per unit"
                        : "Answered once for the property"
                  }
                >
                  <Badge
                    variant="outline"
                    color="gray"
                    radius="sm"
                    leftSection={
                      <ThemeIcon size={12} variant="transparent" color="gray">
                        <IconLock size={10} />
                      </ThemeIcon>
                    }
                  >
                    {sectionTitle(locked.key)}
                  </Badge>
                </Tooltip>
              ))}
            </Group>
          </Stack>
        </Card>
      )}

      {/* Lifecycle action. Any member may start or end (DESIGN §4.2). */}
      {state === "planned" && (
        <Card
          withBorder
          style={{ borderColor: "var(--mantine-color-primary-outline)" }}
          bg="var(--mantine-color-primary-light)"
        >
          <Stack gap="sm">
            <Text size="sm">
              Starting the visit stamps the time and opens every section. Anyone on the tour can
              start it — whoever gets there first.
            </Text>
            <Button
              leftSection={<IconPlayerPlay size={16} />}
              loading={patchVisit.isPending}
              onClick={() => act("start")}
              fullWidth
            >
              Start visit
            </Button>
          </Stack>
        </Card>
      )}

      {state === "in_progress" && (
        <Card>
          <Group justify="space-between" wrap="wrap" gap="sm">
            <Text size="sm" c="dimmed">
              Touring since {dayjs(visit.started_at).format("h:mm A")}.
            </Text>
            <Button
              variant="light"
              leftSection={<IconPlayerStop size={16} />}
              loading={patchVisit.isPending}
              onClick={() => act("end")}
            >
              End visit
            </Button>
          </Group>
        </Card>
      )}

      {state === "completed" && (
        <Card>
          <Group justify="space-between" wrap="wrap" gap="sm">
            <Text size="sm" c="dimmed">
              Toured {dayjs(visit.ended_at).format("ddd D MMM")}. Reopen to add anything you
              remembered afterwards.
            </Text>
            {/* A tour is written on a phone and read on a desktop, and the
                desktop is where the typo gets fixed and the half-heard answer
                finally gets typed. Ending is a state, not a seal — and nothing
                is quietly rewritten, because entries are append-only and every
                one is timestamped and attributed. */}
            <Button
              variant="light"
              leftSection={<IconPlayerPlay size={16} />}
              loading={patchVisit.isPending}
              onClick={() => act("reopen")}
            >
              Reopen visit
            </Button>
          </Group>
        </Card>
      )}

      <VisitConfirmDialog
        opened={cancelOpen}
        onClose={cancelModal.close}
        title="Cancel this visit?"
        body="The visit stays in the list with everything you've recorded — cancelling is not deleting. An agent no-show is worth remembering."
        confirmLabel="Cancel visit"
        loading={patchVisit.isPending}
        reasonLabel="Why? (optional)"
        reasonPlaceholder="agent never showed"
        onConfirm={(reason) => {
          act("cancel", reason);
          cancelModal.close();
        }}
      />

      <VisitConfirmDialog
        opened={deleteOpen}
        onClose={deleteModal.close}
        title="Delete this visit?"
        body="This removes the visit and everything recorded on it, permanently. If the tour simply didn't happen, cancel it instead — that keeps the prep."
        confirmLabel="Delete permanently"
        loading={deleteVisit.isPending}
        onConfirm={() =>
          deleteVisit.mutate(visit.id, {
            onSuccess: () => void navigate(`/h/${huntId}/visits`),
          })
        }
      />
    </Stack>
  );
}
