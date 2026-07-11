import { ActionIcon, Group, Text } from "@mantine/core";
import { IconStar, IconStarFilled } from "@tabler/icons-react";

import { useAuth } from "../../auth/useAuth";
import { useRatings, useSetRating } from "./api";

export function RatingControl({ listingId }: { listingId: string }) {
  const { session } = useAuth();
  const { data: ratings = [] } = useRatings(listingId);
  const setRating = useSetRating(listingId);
  const current = ratings.find((rating) => rating.user_id === session?.user.id)?.rating ?? null;

  return (
    <Group gap={4}>
      <Text size="sm" mr="xs">Your rating</Text>
      {[1, 2, 3, 4, 5].map((value) => {
        const filled = current !== null && value <= current;
        const Icon = filled ? IconStarFilled : IconStar;
        return (
          <ActionIcon key={value} aria-label={`rate ${value}`} color="yellow" onClick={() => setRating.mutate(current === value ? null : value)}>
            <Icon size={18} />
          </ActionIcon>
        );
      })}
    </Group>
  );
}
