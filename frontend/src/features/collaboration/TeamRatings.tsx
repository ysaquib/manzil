import { Avatar, Group, Rating, Stack, Text } from "@mantine/core";

import { useRatings, type HuntContributor, type HuntMember } from "./api";
import { contributorColor, contributorDisplayName } from "./memberDisplay";

export function TeamRatings({
  listingId,
  unitGroupKey,
  members,
  contributors = members,
}: {
  listingId: string;
  unitGroupKey: string;
  members: HuntMember[];
  contributors?: (HuntContributor | HuntMember)[];
  currentUserId?: string;
}) {
  const { data: ratings = [] } = useRatings(listingId);
  const groupRatings = ratings.filter((rating) => rating.unit_group_key === unitGroupKey);
  const byUser = new Map(
    groupRatings.map((rating) => [rating.user_id, rating.rating] as const),
  );
  const present = groupRatings.map((rating) => rating.rating);
  const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
  const initials = (name: string | null) => (name ?? "?").trim().charAt(0).toUpperCase() || "?";
  const currentIds = new Set(members.map((member) => member.user_id));
  const formerRaters = contributors.filter(
    (contributor) =>
      "is_former" in contributor &&
      contributor.is_former &&
      !currentIds.has(contributor.user_id) &&
      byUser.has(contributor.user_id),
  );
  const rows = [...members, ...formerRaters];

  return (
    <Stack
      gap={"xs"}
      pt="sm"
      style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}
    >
      <Group justify="space-between" mb="xs">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" lts="0.06em">
          Hunt ratings
        </Text>
        {avg != null && (
          <Text size="xs" c="text">
            avg {avg.toFixed(1)} · {present.length} rating{present.length === 1 ? "" : "s"}
          </Text>
        )}
      </Group>
      {rows.map((contributor) => {
        const r = byUser.get(contributor.user_id);
        const name = contributorDisplayName(contributor);
        return (
          <Group key={contributor.user_id} gap="xs" py={1} wrap="nowrap">
            <Avatar
              size={26}
              radius="xl"
              styles={{
                placeholder: {
                  backgroundColor: contributorColor(contributor),
                  color: "var(--mantine-color-white)",
                },
              }}
            >
              {initials(name)}
            </Avatar>
            <Text size="sm">{name}</Text>
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
                <Rating
                  value={r}
                  color={contributorColor(contributor)}
                  readOnly
                  fractions={2}
                />
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
