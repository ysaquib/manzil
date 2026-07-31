// Attribution on a shared answer (VC-5, DESIGN §9.7).
//
// Shared items still say who wrote them — that is what `author_user_id` is for,
// and it is why the design needs no second table to attribute them. Colour comes
// from the member's own hunt colour, the same one their ratings and dots use.
import { Group, Text, Tooltip } from "@mantine/core";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";

import type { HuntMember } from "../collaboration/api";
import { memberColor } from "../collaboration/memberColors";
import type { VisitEntry } from "./types";
import classes from "./VisitByline.module.css";

dayjs.extend(relativeTime);

export function VisitByline({
  entry,
  members,
  viewerId,
}: {
  entry: VisitEntry;
  members: HuntMember[];
  viewerId: string | null;
}) {
  const author = members.find((member) => member.user_id === entry.author_user_id);
  // "You" rather than your own name: the byline exists to tell you when somebody
  // *else* wrote the answer you are looking at.
  const name =
    entry.author_user_id === viewerId ? "You" : (author?.display_name ?? "A member");

  return (
    <Group gap={5} wrap="nowrap">
      <Tooltip label={dayjs(entry.created_at).format("ddd D MMM, h:mm A")}>
        <Group gap={5} wrap="nowrap">
          <span
            aria-hidden
            className={classes.dot}
            style={{ backgroundColor: memberColor(author?.color ?? null) }}
          />
          <Text size="xs" c="dimmed">
            {name} · {dayjs(entry.created_at).fromNow()}
          </Text>
        </Group>
      </Tooltip>
    </Group>
  );
}
