// Attribution on a shared answer (VC-5, DESIGN §9.7).
//
// Shared items still say who wrote them — that is what `author_user_id` is for,
// and it is why the design needs no second table to attribute them. Colour comes
// Current authors use their Hunt color; removed authors use the neutral former-
// contributor treatment rather than implying that they remain in the roster.
import { Group, Text, Tooltip } from "@mantine/core";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";

import type { HuntContributor, HuntMember } from "../collaboration/api";
import { contributorColor, contributorDisplayName } from "../collaboration/memberDisplay";
import type { VisitEntry } from "./types";
import classes from "./VisitByline.module.css";

dayjs.extend(relativeTime);

export function VisitByline({
  entry,
  contributors,
  members,
  viewerId,
}: {
  entry: VisitEntry;
  contributors?: (HuntContributor | HuntMember)[];
  /** @deprecated Pass contributors so retained work can include former members. */
  members?: HuntMember[];
  viewerId: string | null;
}) {
  const identities = contributors ?? members ?? [];
  const author = identities.find(
    (contributor) => contributor.user_id === entry.author_user_id,
  );
  // "You" rather than your own name: the byline exists to tell you when somebody
  // *else* wrote the answer you are looking at.
  const name =
    entry.author_user_id === viewerId ? "You" : contributorDisplayName(author);

  return (
    <Group gap={5} wrap="nowrap">
      <Tooltip label={dayjs(entry.created_at).format("ddd D MMM, h:mm A")}>
        <Group gap={5} wrap="nowrap">
          <span
            aria-hidden
            className={classes.dot}
            style={{ backgroundColor: contributorColor(author) }}
          />
          <Text size="xs" c="dimmed">
            {name} · {dayjs(entry.created_at).fromNow()}
          </Text>
        </Group>
      </Tooltip>
    </Group>
  );
}
