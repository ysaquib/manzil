// Sources (P1-11, §13.2): URL, official flag, last_fetched_at, plus the
// listing's Source Policy — read-only in Phase 1 (relaxing it triggers a
// refresh that needs DISCOVER, which is Phase 3).
import { Anchor, Badge, Group, Stack, Text } from "@mantine/core";

import { SOURCE_POLICIES, type SourcePolicy } from "../../lib/contracts";
import type { PropertySource } from "./types";

export function SourcesList({
  sources,
  sourcePolicy,
}: {
  sources: PropertySource[];
  sourcePolicy: SourcePolicy;
}) {
  const policyLabel =
    SOURCE_POLICIES.find((p) => p.value === sourcePolicy)?.label ?? sourcePolicy;
  return (
    <Stack gap="xs">
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
      <Text size="xs" c="dimmed">
        Source policy: {policyLabel}
      </Text>
    </Stack>
  );
}
