import { Group, Rating, Text } from "@mantine/core";

import { useAuth } from "../../auth/useAuth";
import { useMembers, useRatings, useSetRating } from "./api";
import { TeamRatings } from "./TeamRatings";

export function RatingControl({
  listingId,
  unitGroupKey,
  huntId,
  color = "yellow",
}: {
  listingId: string;
  unitGroupKey: string;
  huntId: string;
  color?: string;
}) {
  const { session } = useAuth();
  const { data: ratings = [] } = useRatings(listingId);
  const { data: members = [] } = useMembers(huntId);
  const setRating = useSetRating(listingId, unitGroupKey);
  const current =
    ratings.find(
      (rating) => rating.unit_group_key === unitGroupKey && rating.user_id === session?.user.id,
    )?.rating ?? null;

  return (
    <div>
      <Group gap="md" align="center" mb="sm">
        <Text size="sm" fw={600}>
          Your rating
        </Text>
        <Rating
          value={current ?? 0}
          onChange={(value) => setRating.mutate(value)}
          fractions={2}
          color={color}
          size="lg"
        />
        {current != null && (
          <Text ff="heading" fw={700} ml="auto">
            {current.toFixed(1)}
            <Text span size="xs" c="dimmed">
              /5
            </Text>
          </Text>
        )}
      </Group>
      <TeamRatings
        listingId={listingId}
        unitGroupKey={unitGroupKey}
        members={members}
        currentUserId={session?.user.id}
      />
    </div>
  );
}
