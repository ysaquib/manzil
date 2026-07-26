// Groups the criteria catalog into the rubric page's sections.
//
// Order is decision weight, not the catalog's own order: what you filter on
// first (the unit, the money, the terms, where it is) comes before what you
// merely prefer (fittings, amenities, management). Labels are the renter's
// words rather than the schema's. (DESIGN §20 2026-07-25.)
import type { CatalogEntry } from "./api";

const CATEGORY_ORDER = [
  "unit",
  "cost",
  "tenancy",
  "location",
  "fittings",
  "amenities",
  "management",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  unit: "The unit",
  cost: "Costs",
  tenancy: "Lease terms & rules",
  location: "Location",
  fittings: "Fittings & condition",
  amenities: "Building & amenities",
  management: "Management & service",
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
