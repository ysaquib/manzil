// Read-only rubric view (§13.2): enabled criteria as cards, ordered by position.
import { SimpleGrid, Text } from "@mantine/core";

import type { CatalogEntry, RubricCriterion } from "./api";
import { CriterionViewCard } from "./CriterionViewCard";

export function RubricView({
  saved,
  catalog,
}: {
  saved: RubricCriterion[];
  catalog: CatalogEntry[];
}) {
  const entryByKey = new Map(catalog.map((e) => [e.key, e]));
  const enabled = saved
    .filter((c) => c.enabled)
    .sort((a, b) => a.position - b.position);

  if (enabled.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No criteria enabled — nothing is being scored.
      </Text>
    );
  }

  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
      {enabled.map((criterion) => {
        const entry = entryByKey.get(criterion.catalog_key ?? "");
        return entry ? (
          <CriterionViewCard key={entry.key} criterion={criterion} entry={entry} />
        ) : null;
      })}
    </SimpleGrid>
  );
}
