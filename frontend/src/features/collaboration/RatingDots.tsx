import { Group, Rating, Tooltip } from "@mantine/core";

import type { HuntMember, Rating as RatingType } from "./api";
import { memberColor } from "./memberColors";
import classes from "./RatingDots.module.css";

export function RatingDots({ ratings, members }: { ratings: RatingType[]; members: HuntMember[] }) {
  const byId = new Map(members.map((member) => [member.user_id, member]));
  return (
    <Group gap={4} wrap="nowrap">
      {ratings.map((rating) => {
        const member = byId.get(rating.user_id);
        return (
          <Tooltip key={rating.user_id} label={`${member?.display_name ?? "Member"}: ${rating.rating}/5`}>
            {/* <span aria-label={`${rating.rating} of 5`} style={{ width: 9, height: 9, borderRadius: "50%", background: memberColor(member?.color ?? null), display: "inline-block" }} /> */}
            <Group gap={"xs"}>

            {/* <Text size="xs" lh={1}>{rating.rating}</Text> */}
            <Rating 
              aria-label={`${rating.rating} of 5`}
              value={rating.rating} 
              count={5} 
              fractions={4} 
              readOnly 
              color={memberColor(member?.color ?? "gray")} 
              classNames={{ root: classes.ratingDotsRoot }} 
              maw={16}
            />
            {/* <Badge color={memberColor(member?.color ?? "gray")} leftSection={<IconStarFilled size={8}/>} size="xs">{rating.rating}</Badge> */}
            </Group>
          </Tooltip>
        );
      })}
    </Group>
  );
}
