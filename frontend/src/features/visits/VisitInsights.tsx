// The desktop insight column (VC-14).
//
// Three days after a tour nobody opens a Visit to tick a box. They open it to
// settle an argument — and the argument is always about an Impression, which is
// the one kind of answer that is *per member* and therefore the one a phone
// cannot lay side by side. So the width a desktop has and a phone does not goes
// to exactly that: everyone's ratings in a column each, with the spread
// computed rather than entered.
//
// Read-only throughout. Editing happens in the centre pane, on the row itself;
// this column is the argument, not the form.
import { Box, Group, Progress, Stack, Table, Text, Tooltip } from "@mantine/core";
import dayjs from "dayjs";

import { memberColor } from "../collaboration/memberColors";
import type { HuntMember } from "../collaboration/api";
import { isFlag, meanRating, teamAnswers } from "./entries";
import { toneFor } from "./statusColors";
import type { Visit, VisitEntry, VisitItem } from "./types";
import { isReopened } from "./visitState";
import classes from "./VisitInsights.module.css";

/** Widest minus narrowest. A wide bar is where the conversation needs to be. */
export function spreadOf(values: number[]): number {
  if (values.length < 2) return 0;
  return Math.max(...values) - Math.min(...values);
}

function minutesBetween(from: string | null, to: string | null): number | null {
  if (!from || !to) return null;
  return Math.max(0, Math.round(dayjs(to).diff(dayjs(from), "minute")));
}

function ImpressionCompare({
  items,
  entries,
  activeUnitId,
  members,
  viewerId,
}: {
  items: VisitItem[];
  entries: VisitEntry[];
  activeUnitId: string | null;
  members: HuntMember[];
  viewerId: string | null;
}) {
  // Only rated Impressions compare — a flag is a yes/no tally and free text is
  // not a column. Rows nobody has rated are dropped rather than shown empty.
  const rows = items
    .filter((item) => item.kind === "impression" && !isFlag(item))
    .map((item) => ({ item, answers: teamAnswers(entries, item, activeUnitId) }))
    .filter((row) => row.answers.length > 0);

  if (rows.length === 0) {
    return (
      <Text size="xs" c="dimmed" fs="italic">
        Nobody has rated anything in this section yet.
      </Text>
    );
  }

  // Only members who actually rated something here get a column; a column of
  // dashes for someone who did not attend is noise.
  const raterIds = [
    ...new Set(rows.flatMap((row) => row.answers.map((a) => a.owner_user_id as string))),
  ];
  const raters = raterIds.map((id) => ({
    id,
    member: members.find((candidate) => candidate.user_id === id) ?? null,
  }));

  const widest = Math.max(
    1,
    ...rows.map((row) =>
      spreadOf(row.answers.map((a) => a.value).filter((v): v is number => typeof v === "number")),
    ),
  );

  return (
    <Box className={classes.tableWrap}>
      <Table className={classes.compare} verticalSpacing={4} horizontalSpacing={6}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Impression</Table.Th>
            {raters.map((rater) => (
              <Table.Th key={rater.id} className={classes.numeric}>
                <Tooltip label={rater.member?.display_name ?? "A member"}>
                  <span
                    className={classes.raterDot}
                    style={{ backgroundColor: memberColor(rater.member?.color ?? null) }}
                  >
                    {(rater.member?.display_name ?? "?").slice(0, 1).toUpperCase()}
                  </span>
                </Tooltip>
              </Table.Th>
            ))}
            <Table.Th className={classes.numeric}>Avg</Table.Th>
            <Table.Th className={classes.numeric}>Spread</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map(({ item, answers }) => {
            const numbers = answers
              .map((a) => a.value)
              .filter((v): v is number => typeof v === "number");
            const spread = spreadOf(numbers);
            return (
              <Table.Tr key={item.key}>
                <Table.Td className={classes.rowLabel}>{item.label}</Table.Td>
                {raters.map((rater) => {
                  const answer = answers.find((a) => a.owner_user_id === rater.id);
                  const mine = rater.id === viewerId;
                  return (
                    <Table.Td
                      key={rater.id}
                      className={`${classes.numeric} ${mine ? classes.mine : ""}`}
                    >
                      {typeof answer?.value === "number" ? answer.value : "—"}
                    </Table.Td>
                  );
                })}
                <Table.Td className={classes.numeric}>{meanRating(answers) ?? "—"}</Table.Td>
                <Table.Td className={classes.numeric}>
                  <Tooltip label={`${spread} apart`}>
                    <span className={classes.spread} data-wide={spread >= 3 || undefined}>
                      <i style={{ width: `${(spread / widest) * 100}%` }} />
                    </span>
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      <Text size="xs" c="dimmed" mt={6}>
        Spread is computed, not entered — a wide bar is where the conversation
        needs to happen before anyone signs.
      </Text>
    </Box>
  );
}

export function VisitInsights({
  visit,
  items,
  entries,
  activeUnitId,
  members,
  viewerId,
  answered,
  total,
  openQuestions,
  defectCount,
}: {
  visit: Visit;
  /** The active section's items — the compare table is section-scoped. */
  items: VisitItem[];
  entries: VisitEntry[];
  activeUnitId: string | null;
  members: HuntMember[];
  viewerId: string | null;
  answered: number;
  total: number;
  /** Questions across the whole checklist that nobody has answered yet. */
  openQuestions: VisitItem[];
  defectCount: number;
}) {
  const percent = Math.round((answered / Math.max(total, 1)) * 100);
  const minutes = minutesBetween(visit.started_at, visit.ended_at);
  const critical = openQuestions.filter((item) => item.is_critical);

  return (
    <Stack gap="lg" className={classes.column}>
      <Stack gap={6}>
        <Text className={classes.panelTitle}>This visit</Text>
        <Group gap="sm" align="center" wrap="nowrap">
          <Text fw={700} size="xl" ff="var(--mantine-font-family-headings)">
            {percent}%
          </Text>
          <Box style={{ flex: 1, minWidth: 0 }}>
            <Progress size="sm" value={percent} aria-label="Checklist progress" />
            <Text size="xs" c="dimmed" mt={2}>
              {answered} of {total} in this section
            </Text>
          </Box>
        </Group>
        <Text size="xs" c="dimmed">
          {visit.started_at
            ? dayjs(visit.started_at).format("ddd D MMM · h:mm A")
            : "Not started yet"}
          {minutes !== null ? ` · ${minutes} min` : ""}
        </Text>
        {/* VC-9: the end time survives a reopen, so both can be shown. */}
        {visit.reopened_at && (
          <Text size="xs" c={isReopened(visit) ? "cyan" : "dimmed"}>
            Reopened {dayjs(visit.reopened_at).format("ddd D MMM")}
          </Text>
        )}
        {defectCount > 0 && (
          <Text size="xs" c={toneFor("problem").color}>
            {defectCount === 1 ? "1 defect logged" : `${defectCount} defects logged`}
          </Text>
        )}
      </Stack>

      <Stack gap={6}>
        <Text className={classes.panelTitle}>Impressions, side by side</Text>
        <ImpressionCompare
          items={items}
          entries={entries}
          activeUnitId={activeUnitId}
          members={members}
          viewerId={viewerId}
        />
      </Stack>

      <Stack gap={6}>
        <Text className={classes.panelTitle}>Still unanswered</Text>
        {openQuestions.length === 0 ? (
          <Text size="xs" c="dimmed" fs="italic">
            Every question on the checklist has an answer.
          </Text>
        ) : (
          <Stack gap={5}>
            {critical.slice(0, 4).map((item) => (
              <Group key={item.key} gap={7} wrap="nowrap" align="flex-start">
                <span className={classes.qMark} data-critical aria-hidden />
                <Text size="xs" style={{ minWidth: 0 }}>
                  {item.label}{" "}
                  <Text span size="xs" fw={600} c={toneFor("problem").color}>
                    critical
                  </Text>
                </Text>
              </Group>
            ))}
            <Text size="xs" c="dimmed">
              {openQuestions.length} unanswered
              {critical.length > 0 ? `, ${critical.length} of them critical` : ""}.
            </Text>
          </Stack>
        )}
      </Stack>
    </Stack>
  );
}
