// Who else is in this Visit (VC-5, DESIGN §9.7, §13.3).
//
// Ambient, never modal: an avatar row and one quiet line. No toasts — you are
// holding the phone in one hand and a tape measure in the other.
import { Avatar, Group, Text, Tooltip } from "@mantine/core";

import { memberColor } from "../collaboration/memberColors";
import type { HuntMember } from "../collaboration/api";
import type { PresentMember } from "./usePresence";
import { sectionTitle } from "./visitState";
import classes from "./VisitPresence.module.css";

export function initialsFor(name: string | null | undefined): string {
  return (name ?? "?").trim().charAt(0).toUpperCase() || "?";
}

/** "Sana is in the Kitchen" / "Sana and Dan are here" / "3 others are here". */
export function presenceSentence(
  present: PresentMember[],
  nameOf: (userId: string) => string,
): string | null {
  if (present.length === 0) return null;
  if (present.length === 1) {
    const [only] = present;
    return only.sectionKey
      ? `${nameOf(only.userId)} is in ${sectionTitle(only.sectionKey)}`
      : `${nameOf(only.userId)} is here`;
  }
  if (present.length === 2) {
    return `${nameOf(present[0].userId)} and ${nameOf(present[1].userId)} are here`;
  }
  return `${present.length} others are here`;
}

export function VisitPresence({
  present,
  members,
}: {
  present: PresentMember[];
  members: HuntMember[];
}) {
  if (present.length === 0) return null;

  const memberFor = (userId: string) => members.find((member) => member.user_id === userId);
  const nameOf = (userId: string) => memberFor(userId)?.display_name ?? "Someone";

  return (
    <Group gap={8} wrap="nowrap" className={classes.bar}>
      <Avatar.Group spacing="xs">
        {present.map((person) => {
          const member = memberFor(person.userId);
          return (
            <Tooltip
              key={person.userId}
              label={
                person.sectionKey
                  ? `${nameOf(person.userId)} — ${sectionTitle(person.sectionKey)}`
                  : nameOf(person.userId)
              }
            >
              <Avatar
                size={24}
                radius="xl"
                className={classes.live}
                styles={{
                  placeholder: {
                    backgroundColor: memberColor(member?.color ?? null),
                    color: "var(--mantine-color-white)",
                    fontSize: 11,
                    fontWeight: 700,
                  },
                }}
              >
                {initialsFor(member?.display_name)}
              </Avatar>
            </Tooltip>
          );
        })}
      </Avatar.Group>
      <Text size="xs" c="dimmed">
        {presenceSentence(present, nameOf)}
      </Text>
    </Group>
  );
}
