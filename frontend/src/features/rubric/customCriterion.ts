import type { CatalogEntry, CustomCriterionDef, RubricCriterion } from "./api";

export function criterionKey(criterion: RubricCriterion): string | null {
  return criterion.catalog_key ?? criterion.custom_def?.key ?? null;
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
  };
}
