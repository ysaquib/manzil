import { Group, Tooltip } from "@mantine/core";

import type { HuntMember, Rating } from "./api";
import { memberColor } from "./memberColors";

export function RatingDots({ ratings, members }: { ratings: Rating[]; members: HuntMember[] }) {
  const byId = new Map(members.map((member) => [member.user_id, member]));
  return (
    <Group gap={4} wrap="nowrap">
      {ratings.map((rating) => {
        const member = byId.get(rating.user_id);
        return (
          <Tooltip key={rating.user_id} label={`${member?.display_name ?? "Member"}: ${rating.rating}/5`}>
            <span aria-label={`${rating.rating} of 5`} style={{ width: 9, height: 9, borderRadius: "50%", background: memberColor(member?.color ?? null), display: "inline-block" }} />
          </Tooltip>
        );
      })}
    </Group>
  );
}
