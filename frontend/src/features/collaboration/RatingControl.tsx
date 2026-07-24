import { Group, Rating, Text } from "@mantine/core";

import { useAuth } from "../../auth/useAuth";
import { useMembers, useRatings, useSetRating } from "./api";
import { starColorCss } from "./memberColors";
import { TeamRatings } from "./TeamRatings";

export function RatingControl({
  listingId,
  unitGroupKey,
  huntId,
}: {
  listingId: string;
  unitGroupKey: string;
  huntId: string;
}) {
  const { session } = useAuth();
  const { data: ratings = [] } = useRatings(listingId);
  const { data: members = [] } = useMembers(huntId);
  const setRating = useSetRating(listingId, unitGroupKey);
  const current =
    ratings.find(
      (rating) => rating.unit_group_key === unitGroupKey && rating.user_id === session?.user.id,
    )?.rating ?? null;
  const currentMember = members.find((member) => member.user_id === session?.user.id);
  const yourStarColor = starColorCss(currentMember?.color ?? null);

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
          color={yourStarColor}
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
