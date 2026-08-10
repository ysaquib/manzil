import type { CatalogEntry, CustomCriterionDef, RubricCriterion } from "./api";

export function criterionKey(criterion: RubricCriterion): string | null {
  return criterion.catalog_key ?? criterion.custom_def?.key ?? null;
}

/** Global catalog plus synthetic entries for hunt custom Criteria. */
export function catalogWithCustomLabels(
  catalog: CatalogEntry[],
  rubric: RubricCriterion[],
): CatalogEntry[] {
  const merged = [...catalog];
  for (const criterion of rubric) {
    if (criterion.catalog_key === null && criterion.custom_def) {
      merged.push(customCatalogEntry(criterion.custom_def));
    }
  }
  return merged;
}

export function labelByKeyFromCatalog(catalog: CatalogEntry[]): Map<string, string> {
  return new Map(catalog.map((entry) => [entry.key, entry.label]));
}

export function customCatalogEntry(custom: CustomCriterionDef): CatalogEntry {
  return {
    key: custom.key,
    label: custom.label,
    category: "custom",
    domain: "rent",
    fact_scope: custom.fact_scope,
    value_schema: custom.value_schema,
    default_options: [],
    extraction_hint: custom.description,
    requires_tool: custom.requires_tool,
    refresh_class: custom.refresh_class,
    acquisition: custom.acquisition ?? "extracted",
  };
}
