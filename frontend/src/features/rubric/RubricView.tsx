// Read-only rubric view (§13.2): enabled criteria as cards, grouped by category
// and ordered by position.
//
// Cards size to their own content (`alignItems: start`) instead of stretching to
// the tallest card in the row — the stretch was most of the page's whitespace
// (UI Decision Log 2026-07-25).
import { SimpleGrid, Stack, Text } from "@mantine/core";

import type { CatalogEntry, RubricCriterion } from "./api";
import { CriterionGroupHeader } from "./CriterionGroupHeader";
import { CriterionViewCard } from "./CriterionViewCard";
import { groupCatalog } from "./catalogGroups";
import { customCatalogEntry } from "./customCriterion";

export function RubricView({
  saved,
  catalog,
}: {
  saved: RubricCriterion[];
  catalog: CatalogEntry[];
}) {
  const enabled = saved
    .filter((c) => c.enabled)
    .sort((a, b) => a.position - b.position);
  const enabledByKey = new Map(
    enabled.filter((criterion) => criterion.catalog_key !== null).map((criterion) => [criterion.catalog_key, criterion]),
  );
  const enabledCatalog = catalog.filter((entry) => enabledByKey.has(entry.key));
  const enabledCustom = enabled.filter(
    (criterion) => criterion.custom_def !== null,
  );

  if (enabled.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No criteria enabled — nothing is being scored.
      </Text>
    );
  }

  return (
    <Stack gap="lg">
      {groupCatalog(enabledCatalog).map((group) => (
        <Stack gap="sm" key={group.category}>
          <CriterionGroupHeader
            label={group.label}
            category={group.category}
            count={`${group.entries.length} scored`}
          />
          <SimpleGrid
            cols={{ base: 1, sm: 2, lg: 3, xl: 4 }}
            spacing="md"
            style={{ alignItems: "start" }}
          >
            {group.entries.map((entry) => {
              const criterion = enabledByKey.get(entry.key);
              return criterion ? (
                <CriterionViewCard key={entry.key} criterion={criterion} entry={entry} />
              ) : null;
            })}
          </SimpleGrid>
        </Stack>
      ))}
      {enabledCustom.length > 0 && (
        <Stack gap="sm">
          <CriterionGroupHeader
            label="Custom"
            category="custom"
            count={`${enabledCustom.length} scored`}
          />
          <SimpleGrid
            cols={{ base: 1, sm: 2, lg: 3, xl: 4 }}
            spacing="md"
            style={{ alignItems: "start" }}
          >
            {enabledCustom.map((criterion) => {
              const custom = criterion.custom_def;
              if (custom === null) return null;
              return (
                <CriterionViewCard
                  key={custom.key}
                  criterion={criterion}
                  entry={customCatalogEntry(custom)}
                />
              );
            })}
          </SimpleGrid>
        </Stack>
      )}
    </Stack>
  );
}
