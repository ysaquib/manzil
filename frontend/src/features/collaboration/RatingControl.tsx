import { Group, Text } from "@mantine/core";
import { Rating } from "@mantine/core";
import { useAuth } from "../../auth/useAuth";
import { useRatings, useSetRating } from "./api";

export function RatingControl({ listingId, color="blue" }: { listingId: string, color?: string }) {
  const { session } = useAuth();
  const { data: ratings = [] } = useRatings(listingId);
  const setRating = useSetRating(listingId);
  const current = ratings.find((rating) => rating.user_id === session?.user.id)?.rating ?? null;

  return (
    <Group gap={4}>
      <Text size="sm" mr="xs">Your rating</Text>
      <Rating 
        value={current ?? 0} 
        onChange={(value) => setRating.mutate(value)} 
        color={color} 
        size="md"
      />
    </Group>
  );
}
