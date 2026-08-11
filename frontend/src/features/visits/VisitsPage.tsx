// Visits list (VC-2, DESIGN §13.2). Every tour of this hunt's properties, by
// derived state. One row says which property, which units, who set it up, and
// what state it is in.
import {
  Alert,
  Anchor,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  SegmentedControl,
  Skeleton,
  Stack,
  Text,
} from "@mantine/core";
import { IconFlag, IconPlus } from "@tabler/icons-react";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { useHuntContributors } from "../collaboration/api";
import { contributorDisplayName } from "../collaboration/memberDisplay";
import { useVisits } from "./api";
import type { Visit, VisitState } from "./types";
import { VisitStatePill } from "./VisitStatePill";
import { VisitUnitChips } from "./VisitUnitChips";
import { countByState, filterByState, visitState } from "./visitState";
import classes from "./VisitsPage.module.css";

type Filter = VisitState | "all";

/** Planned tours read forward ("Thu 31 Jul"); past ones read back ("2 days ago"). */
function whenLabel(visit: Visit): string {
  const state = visitState(visit);
  if (state === "planned" && visit.scheduled_for) {
    const when = dayjs(visit.scheduled_for);
    const prefix = when.isBefore(dayjs()) ? "Was due" : "Scheduled";
    return `${prefix} ${when.format("ddd D MMM, h:mm A")}`;
  }
  const anchor = visit.started_at ?? visit.created_at;
  return dayjs(anchor).format("ddd D MMM, h:mm A");
}

function VisitRow({
  visit,
  huntId,
  memberName,
}: {
  visit: Visit;
  huntId: string;
  memberName: (userId: string) => string;
}) {
  const state = visitState(visit);
  const units = visit.visit_units ?? [];
  return (
    // Report 10: the whole row is one link. Wrapping only the title meant the
    // 90% of the card that looks clickable was not, and the state pill and unit
    // chips beside it read as targets while doing nothing.
    <Link
      to={`/h/${huntId}/visits/${visit.id}`}
      className={classes.cardLink}
      // Cancelled visits stay in the list at reduced emphasis: an agent
      // no-showing is information about the property, and the prep survives.
      style={{ opacity: state === "cancelled" ? 0.62 : 1 }}
    >
      <Group align="flex-start" wrap="nowrap" gap="md" py="sm">
      <Stack gap={6} style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} ff="var(--mantine-font-family-headings)" size="md" lh={1.25}>
            {visit.property?.name ?? "Unknown property"}
          </Text>
        <Text size="xs" c="dimmed">
          {whenLabel(visit)} · set up by {memberName(visit.created_by)}
          {visit.cancel_reason ? ` · ${visit.cancel_reason}` : ""}
        </Text>
        <VisitUnitChips units={units} />
      </Stack>
      <Stack gap={4} align="flex-end" style={{ flex: "none" }}>
        <VisitStatePill state={state} />
        <Text size="xs" c="dimmed">
          {units.length === 1 ? "1 unit" : `${units.length} units`}
        </Text>
      </Stack>
      </Group>
    </Link>
  );
}

export function VisitsPage() {
  const { huntId = "" } = useParams();
  const [filter, setFilter] = useState<Filter>("all");
  const visitsQuery = useVisits(huntId);
  const contributorsQuery = useHuntContributors(huntId);

  const visits = visitsQuery.data ?? [];
  const counts = useMemo(() => countByState(visits), [visits]);
  const shown = useMemo(() => filterByState(visits, filter), [visits, filter]);

  const memberName = (userId: string) =>
    contributorDisplayName(
      contributorsQuery.data?.find((contributor) => contributor.user_id === userId),
    );

  return (
    <Stack gap="lg">
      <PageHeader
        title="Visits"
        description="Every tour of this hunt's properties — planned, in progress and done."
        rightSlot={
          <Button
            component={Link}
            to={`/h/${huntId}/visits/new`}
            leftSection={<IconPlus size={16} />}
          >
            New visit
          </Button>
        }
      />

      {visitsQuery.isError && (
        <Alert color="red" title="Couldn't load visits">
          {(visitsQuery.error as Error).message}
        </Alert>
      )}

      {visits.length > 0 && (
        <SegmentedControl
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
          data={[
            { value: "all", label: `All ${counts.all}` },
            { value: "planned", label: `Planned ${counts.planned}` },
            { value: "in_progress", label: `In progress ${counts.in_progress}` },
            { value: "completed", label: `Done ${counts.completed}` },
            ...(counts.cancelled > 0
              ? [{ value: "cancelled", label: `Cancelled ${counts.cancelled}` }]
              : []),
          ]}
          // Four-to-five options do not fit a phone in one row.
          styles={{ root: { flexWrap: "wrap" } }}
        />
      )}

      {visitsQuery.isLoading ? (
        <Card>
          <Stack gap="md">
            <Skeleton height={44} />
            <Skeleton height={44} />
            <Skeleton height={44} />
          </Stack>
        </Card>
      ) : visits.length === 0 ? (
        <Card>
          <Center py="xl">
            <Stack align="center" gap="xs" maw={420}>
              <IconFlag size={26} stroke={1.5} color="var(--mantine-color-dimmed)" />
              <Text fw={600}>No visits yet</Text>
              <Text size="sm" c="dimmed" ta="center">
                Set one up before you tour, and the checklist is ready on your phone when you
                get there — with the prep questions answered on the couch.
              </Text>
              <Button
                component={Link}
                to={`/h/${huntId}/visits/new`}
                variant="light"
                mt="xs"
                leftSection={<IconPlus size={16} />}
              >
                Plan your first visit
              </Button>
            </Stack>
          </Center>
        </Card>
      ) : shown.length === 0 ? (
        <Card>
          <Center py="lg">
            <Text size="sm" c="dimmed">
              No visits in that state.{" "}
              <Anchor component="button" type="button" onClick={() => setFilter("all")}>
                Show all {counts.all}
              </Anchor>
            </Text>
          </Center>
        </Card>
      ) : (
        <Card padding="md">
          <Stack gap={0}>
            {shown.map((visit, index) => (
              <Box
                key={visit.id}
                style={
                  index === 0
                    ? undefined
                    : { borderTop: "1px solid var(--mantine-color-default-border)" }
                }
              >
                <VisitRow visit={visit} huntId={huntId} memberName={memberName} />
              </Box>
            ))}
          </Stack>
        </Card>
      )}

      {contributorsQuery.isLoading && visits.length > 0 && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="xs" c="dimmed">
            Loading names…
          </Text>
        </Group>
      )}
    </Stack>
  );
}
