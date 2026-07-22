import type { CatalogEntry } from "./api";

const CATEGORY_ORDER = [
  "property",
  "unit",
  "policy",
  "cost",
  "availability",
  "condition",
  "location",
  "reputation",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  property: "Property",
  unit: "Floor plan and unit",
  policy: "Policies",
  cost: "Costs",
  availability: "Availability",
  condition: "Condition",
  location: "Location",
  reputation: "Reputation",
};

export interface CatalogGroup {
  category: string;
  label: string;
  entries: CatalogEntry[];
}

export function groupCatalog(catalog: CatalogEntry[]): CatalogGroup[] {
  const buckets = new Map<string, CatalogEntry[]>();
  for (const entry of catalog) {
    const bucket = buckets.get(entry.category);
    if (bucket) bucket.push(entry);
    else buckets.set(entry.category, [entry]);
  }
  const order = new Map<string, number>(CATEGORY_ORDER.map((category, index) => [category, index]));
  return [...buckets]
    .sort(([left], [right]) =>
      (order.get(left) ?? CATEGORY_ORDER.length) - (order.get(right) ?? CATEGORY_ORDER.length) ||
      left.localeCompare(right),
    )
    .map(([category, entries]) => ({
      category,
      label: CATEGORY_LABELS[category] ?? category.replaceAll("_", " "),
      entries,
    }));
}
