// The drawer's Visits section (VC-8, DESIGN §9.7, §13.2).
//
// Every tour of this Property, newest first. This is where a described unit
// that matched no advertised Unit Group stays visible: the Overview cannot show
// it — minting a Unit Group would contradict §3 — but the tour still happened,
// and the drawer is where the whole record lives rather than the roll-up.
import { Badge, Group, Stack, Text } from "@mantine/core";
import { IconStarFilled } from "@tabler/icons-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import { Link } from "react-router-dom";

import { usePropertyVisits, useVisitUnitGroupScores, visitScoreKey } from "./api";
import type { Visit } from "./types";
import { VisitStatePill } from "./VisitStatePill";
import { visitState } from "./visitState";
import { formatVisitScore } from "./VisitScoreCell";

dayjs.extend(relativeTime);

/** When a tour happened, or was meant to. */
export function visitWhen(visit: Visit): string {
  const at = visit.started_at ?? visit.scheduled_for ?? visit.created_at;
  return dayjs(at).format("ddd D MMM");
}

export function ListingVisits({
  huntId,
  propertyId,
  huntListingId,
}: {
  huntId: string;
  propertyId: string | undefined;
  huntListingId: string;
}) {
  const { data: visits = [], isLoading } = usePropertyVisits(huntId, propertyId);
  const { data: scores = [] } = useVisitUnitGroupScores(huntId);
  const scoreByGroup = new Map(
    scores.map((entry) => [visitScoreKey(entry.hunt_listing_id, entry.unit_group_key), entry]),
  );

  if (isLoading) {
    return (
      <Text size="sm" c="dimmed">
        Loading visits…
      </Text>
    );
  }

  if (visits.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No one has toured this property yet.
      </Text>
    );
  }

  return (
    <Stack gap="sm">
      {visits.map((visit) => {
        const units = [...(visit.visit_units ?? [])].sort(
          (a, b) => a.display_order - b.display_order,
        );
        return (
          <Stack key={visit.id} gap={4}>
            <Group gap="xs" wrap="wrap">
              <Text
                size="sm"
                fw={600}
                component={Link}
                to={`/h/${huntId}/visits/${visit.id}`}
                onClick={(event) => event.stopPropagation()}
              >
                {visitWhen(visit)}
              </Text>
              <VisitStatePill state={visitState(visit)} />
              <Text size="xs" c="dimmed">
                {dayjs(visit.started_at ?? visit.created_at).fromNow()}
              </Text>
            </Group>

            <Group gap={6} wrap="wrap">
              {units.length === 0 && (
                <Text size="xs" c="dimmed">
                  No units recorded
                </Text>
              )}
              {units.map((unit) => {
                const entry = scoreByGroup.get(visitScoreKey(huntListingId, unit.unit_group_key));
                // A unit whose group the Property does not advertise has no
                // roll-up row by design; it is still shown here, because it is
                // still a door somebody walked.
                const representsThisUnit = entry?.best_visit_unit_id === unit.id;
                return (
                  <Badge
                    key={unit.id}
                    size="sm"
                    radius="sm"
                    variant="light"
                    color={unit.floor_plan_id ? "gray" : "teal"}
                    leftSection={
                      representsThisUnit ? <IconStarFilled size={9} aria-hidden /> : undefined
                    }
                  >
                    {unit.label}
                    {representsThisUnit && entry ? ` · ${formatVisitScore(entry.score)}` : ""}
                  </Badge>
                );
              })}
            </Group>
          </Stack>
        );
      })}
    </Stack>
  );
}
