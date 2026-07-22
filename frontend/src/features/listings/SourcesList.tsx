// Sources (P3-5, §13.2): retained links, fetch state, assurance badge, and the
// Listing's editable Source Policy. Relaxing the policy queues DISCOVER.
import { Anchor, Badge, Group, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";

import { SingleSourceBadge } from "../../components/badges/ListingBadges";
import { SOURCE_POLICIES, type SourcePolicy } from "../../lib/contracts";
import { usePatchSourcePolicy } from "./api";
import type { PropertySource, SingleSourceReason } from "./types";

export function SourcesList({
  sources,
  sourcePolicy,
  huntId,
  listingId,
  singleSourceReason,
  canEdit,
}: {
  sources: PropertySource[];
  sourcePolicy: SourcePolicy;
  huntId: string;
  listingId: string;
  singleSourceReason: SingleSourceReason | null;
  canEdit: boolean;
}) {
  const patchPolicy = usePatchSourcePolicy(huntId);
  const changePolicy = (value: string | null) => {
    if (!value || value === sourcePolicy) return;
    patchPolicy.mutate(
      { listingId, sourcePolicy: value as SourcePolicy },
      {
        onError: (error) => notifications.show({
          color: "red",
          title: "Could not update Source Policy",
          message: error instanceof Error ? error.message : "Try again.",
        }),
      },
    );
  };
  return (
    <Stack gap="xs">
      {singleSourceReason && <SingleSourceBadge reason={singleSourceReason} />}
      {sources.map((source) => (
        <Group key={source.id} gap="xs" wrap="nowrap">
          <Anchor href={source.url} target="_blank" rel="noreferrer" size="sm" lineClamp={1}>
            {source.site_domain}
          </Anchor>
          {source.is_official && (
            <Badge size="xs" variant="light">
              official
            </Badge>
          )}
          <Text size="xs" c="dimmed">
            {source.last_fetched_at
              ? `fetched ${new Date(source.last_fetched_at).toLocaleDateString()}`
              : "not fetched yet"}
          </Text>
        </Group>
      ))}
      {sources.length === 0 && (
        <Text size="sm" c="dimmed">
          No sources recorded yet.
        </Text>
      )}
      <Select
        label="Source Policy"
        description="Relaxing this policy starts a source-discovery refresh."
        data={SOURCE_POLICIES}
        value={sourcePolicy}
        onChange={changePolicy}
        disabled={!canEdit || patchPolicy.isPending}
        allowDeselect={false}
        size="xs"
      />
    </Stack>
  );
}
