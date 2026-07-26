// Team opinion in one cell: the average, who weighed in, and how much they
// said (UI Decision Log 2026-07-26).
//
// Replaces five read-only Mantine `Rating` widgets crushed into `maw={16}`,
// where the stars overlapped into an unreadable smear at two members and the
// cell outgrew the score column at five. Count of dots answers "how many",
// colour answers "who", hover answers "exactly what".
import { Box, Group, Text, Tooltip } from "@mantine/core";
import { IconMessageCircle, IconStarFilled } from "@tabler/icons-react";

import type { HuntMember, Rating } from "./api";
import { memberColor } from "./memberColors";
import classes from "./RatingSummary.module.css";

export function averageRating(ratings: Rating[]): number | null {
  if (ratings.length === 0) return null;
  return ratings.reduce((sum, r) => sum + r.rating, 0) / ratings.length;
}

/** One decimal, but never a trailing ".0" — 4 reads as "4", 4.25 as "4.3". */
export function formatAverage(average: number): string {
  const rounded = Math.round(average * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

export function RatingSummary({
  ratings,
  members,
  commentCount = 0,
}: {
  ratings: Rating[];
  members: HuntMember[];
  commentCount?: number;
}) {
  const byId = new Map(members.map((member) => [member.user_id, member]));
  const average = averageRating(ratings);

  return (
    <Group gap="sm" wrap="nowrap">
      <Group gap={6} wrap="nowrap">
        {average === null ? (
          <Text size="sm" c="dimmed" aria-label="no ratings yet">
            —
          </Text>
        ) : (
          <Group gap={4} wrap="nowrap">
            <IconStarFilled size={11} className={classes.star} />
            <Text className={classes.average} aria-label={`average ${formatAverage(average)} of 5`}>
              {formatAverage(average)}
            </Text>
          </Group>
        )}
        <Group gap={3} wrap="nowrap">
          {ratings.map((rating) => {
            const member = byId.get(rating.user_id);
            return (
              <Tooltip
                key={rating.user_id}
                label={`${member?.display_name ?? "Member"}: ${rating.rating}/5`}
                openDelay={200}
              >
                <Box
                  className={classes.dot}
                  style={{ background: memberColor(member?.color ?? null) }}
                  role="img"
                  aria-label={`${member?.display_name ?? "Member"}: ${rating.rating} of 5`}
                />
              </Tooltip>
            );
          })}
        </Group>
      </Group>

      {commentCount > 0 && (
        <Tooltip
          label={`${commentCount} comment${commentCount === 1 ? "" : "s"}`}
          openDelay={200}
        >
          <Group gap={4} wrap="nowrap" c="dimmed">
            <IconMessageCircle size={13} stroke={1.5} />
            <Text className={classes.average} aria-label={`${commentCount} comments`}>
              {commentCount}
            </Text>
          </Group>
        </Tooltip>
      )}
    </Group>
  );
}
