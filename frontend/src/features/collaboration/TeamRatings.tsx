import { Avatar, Box, Group, Rating, Stack, Text } from "@mantine/core";

import { useRatings, type HuntMember } from "./api";
import { memberColor, starColorCss } from "./memberColors";

export function TeamRatings({
  listingId,
  unitGroupKey,
  members,
}: {
  listingId: string;
  unitGroupKey: string;
  members: HuntMember[];
  currentUserId?: string;
}) {
  const { data: ratings = [] } = useRatings(listingId);
  const byUser = new Map(
    ratings
      .filter((r) => r.unit_group_key === unitGroupKey)
      .map((r) => [r.user_id, r.rating] as const),
  );
  const present = members
    .map((m) => byUser.get(m.user_id))
    .filter((v): v is number => v != null);
  const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
  const initials = (name: string | null) => (name ?? "?").trim().charAt(0).toUpperCase() || "?";

  return (
    <Stack
      gap={0}
      pt="sm"
      style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}
    >
      <Group justify="space-between" mb="xs">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" lts="0.06em">
          The team
        </Text>
        {avg != null && (
          <Text size="xs" c="text">
            avg {avg.toFixed(1)} · {present.length} of {members.length} rated
          </Text>
        )}
      </Group>
      {members.map((m) => {
        const r = byUser.get(m.user_id);
        return (
          <Group key={m.user_id} gap="xs" py={1} wrap="nowrap">
            <Avatar
              size={26}
              radius="xl"
              styles={{
                placeholder: {
                  backgroundColor: memberColor(m.color),
                  color: "var(--mantine-color-white)",
                },
              }}
            >
              {initials(m.display_name)}
            </Avatar>
            <Text size="sm">{m.display_name ?? "Member"}</Text>
            {r != null ? (
              <Group gap="xs" ml="auto">
                <Text
                  size="sm"
                  lh={1}
                  w={26}
                  ta="right"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {r.toFixed(1)}
                </Text>
                  <Rating value={r} color={starColorCss(m.color)} readOnly fractions={2}/>
              </Group>
            ) : (
              <Text size="xs" c="dimmed" fs="italic" ml="auto">
                Not rated yet
              </Text>
            )}
          </Group>
        );
      })}
    </Stack>
  );
}
