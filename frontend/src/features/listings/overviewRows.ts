// Overview row building, filtering, sorting (P1-10). Pure and unit-tested;
// the table component stays declarative.
import { cityFilterMatches, propertyLocationLabel } from "./locality";
import type { AllInComponents, InterestStatus, Listing, UnitGroupState } from "./types";
import { deriveUnitGroups, type UnitGroupRow } from "./unitGroups";

export type StatusFilter = InterestStatus | "undecided";

export interface OverviewRow {
  listing: Listing;
  // null → a listing-level row: the listing has no unit groups yet, either
  // because it is still ingesting (pending) or because ingest found no available
  // floor plans (no-availability, §8.2). See `rowAvailability`.
  group: UnitGroupRow | null;
  state: UnitGroupState | null;
}

export function buildRows(listings: Listing[], states: UnitGroupState[] = []): OverviewRow[] {
  const stateByKey = new Map(
    states.map((state) => [`${state.hunt_listing_id}:${state.unit_group_key}`, state]),
  );
  return listings.flatMap((listing): OverviewRow[] => {
    const groups = deriveUnitGroups(listing);
    // A listing with no scorable plans still gets exactly one row so it stays
    // visible — dimmed for no-availability, "pending" while it ingests.
    if (groups.length === 0) return [{ listing, group: null, state: null }];
    return groups.map((group) => ({
      listing,
      group,
      state: stateByKey.get(`${listing.id}:${group.key}`) ?? null,
    }));
  });
}

export type RowAvailability = "scored" | "pending" | "unavailable";

// Which of the three terminal-ish states a row is in. `unavailable` is a
// legitimate "no available floor plans" result (§8.2), distinct from an error
// (a failed job never produces a row here) and from `pending` (still ingesting).
export function rowAvailability(row: OverviewRow): RowAvailability {
  if (row.group === null) return row.listing.unavailable_at ? "unavailable" : "pending";
  return row.group.displayScore ? "scored" : "pending";
}

// Catalog enum vocabularies (§8.2 criteria_catalog) the enum filters accept.
export const LAUNDRY_VALUES = ["in_unit", "hookups", "on_site", "none"] as const;
export const PARKING_VALUES = [
  "garage", "carport", "covered", "dedicated_lot", "street_only", "none",
] as const;
export const PETS_VALUES = ["cats_and_dogs", "cats_only", "dogs_only", "none"] as const;
export const COOLING_VALUES = ["central", "window_units", "none"] as const;

export interface OverviewFilterState {
  /** Free-text property name / address substring; null when off. */
  query: string | null;
  minScore: number | null;
  maxScore: number | null;
  minRent: number | null;
  maxRent: number | null;
  minSqft: number | null;
  maxSqft: number | null;
  minBeds: number | null;
  maxBeds: number | null;
  minBaths: number | null;
  maxBaths: number | null;
  cities: string[];
  statuses: StatusFilter[];
  visited: boolean | null;
  availabilities: RowAvailability[];
  laundry: string[];
  parking: string[];
  pets: string[];
  cooling: string[];
  dishwasher: boolean | null;
  maxAllIn: number | null;
  /** ISO date: a group passes when some plan is available on or before it. */
  availableBy: string | null;
}

export const DEFAULT_OVERVIEW_FILTERS: OverviewFilterState = {
  query: null,
  minScore: null,
  maxScore: null,
  minRent: null,
  maxRent: null,
  minSqft: null,
  maxSqft: null,
  minBeds: null,
  maxBeds: null,
  minBaths: null,
  maxBaths: null,
  cities: [],
  statuses: [],
  visited: null,
  availabilities: [],
  laundry: [],
  parking: [],
  pets: [],
  cooling: [],
  dishwasher: null,
  maxAllIn: null,
  availableBy: null,
};

// Rehydrate a possibly stale/foreign filter object (hunt_shared_filters rows
// written before a filter was added, or after one is removed): unknown keys
// drop, missing or ill-typed keys default. Never throws.
export function sanitizeFilterState(input: unknown): OverviewFilterState {
  const raw = (typeof input === "object" && input !== null ? input : {}) as Record<
    string,
    unknown
  >;
  const out = { ...DEFAULT_OVERVIEW_FILTERS };
  for (const key of Object.keys(DEFAULT_OVERVIEW_FILTERS) as FilterPillKey[]) {
    const fallback = DEFAULT_OVERVIEW_FILTERS[key];
    const value = raw[key];
    if (Array.isArray(fallback)) {
      if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
        (out[key] as string[]) = value as string[];
      }
    } else if (value === null || typeof value === typeof exemplarFor(key)) {
      (out[key] as unknown) = value === undefined ? fallback : value;
    }
  }
  return out;
}

// A representative non-null value per scalar filter key, for typeof checks.
function exemplarFor(key: FilterPillKey): unknown {
  if (key === "visited" || key === "dishwasher") return true;
  if (key === "availableBy" || key === "query") return "";
  return 0;
}

/** Order-insensitive equality — drives the hunt-wide vs modified badge. */
export function filtersEqual(a: OverviewFilterState, b: OverviewFilterState): boolean {
  return (Object.keys(DEFAULT_OVERVIEW_FILTERS) as FilterPillKey[]).every((key) => {
    const va = a[key];
    const vb = b[key];
    if (Array.isArray(va) && Array.isArray(vb)) {
      if (va.length !== vb.length) return false;
      const sb = [...vb].sort();
      return [...va].sort().every((v, i) => v === sb[i]);
    }
    return va === vb;
  });
}

export function hasActiveFilters(filters: OverviewFilterState): boolean {
  return Object.values(filters).some((v) => (Array.isArray(v) ? v.length > 0 : v !== null));
}

// Free-text search: case-insensitive substring over property name + address.
// A whitespace-only query is inert (the input clears to null, but a stray
// shared-filter value must not hide every row).
function queryPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  const needle = filters.query?.trim().toLowerCase();
  if (!needle) return true;
  const property = row.listing.property;
  return (
    property.name.toLowerCase().includes(needle) ||
    property.canonical_address.toLowerCase().includes(needle)
  );
}

function rangeOverlaps(
  rowMin: number | null,
  rowMax: number | null,
  filterMin: number | null,
  filterMax: number | null,
): boolean {
  if (rowMin === null && rowMax === null) return true;
  const lo = rowMin ?? rowMax ?? 0;
  const hi = rowMax ?? rowMin ?? 0;
  const fLo = filterMin ?? -Infinity;
  const fHi = filterMax ?? Infinity;
  return lo <= fHi && hi >= fLo;
}

// `hide score < N` (§13.2, §9.3 rationale): declutters gate-zeroed rows
// without deleting the "why we rejected it" record. Unscored rows stay
// visible — pending ingestion is not a verdict.
function scorePredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.minScore === null && filters.maxScore === null) return true;
  if (row.group?.displayScore == null) return true;
  return scalarInBounds(row.group.displayScore.total, filters.minScore, filters.maxScore);
}

function rentPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.minRent === null && filters.maxRent === null) return true;
  if (row.group === null) return true;
  return rangeOverlaps(
    row.group.rentMin,
    row.group.rentMax,
    filters.minRent,
    filters.maxRent,
  );
}

function sqftPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.minSqft === null && filters.maxSqft === null) return true;
  if (row.group === null) return true;
  return rangeOverlaps(
    row.group.sqftMin,
    row.group.sqftMax,
    filters.minSqft,
    filters.maxSqft,
  );
}

function scalarInBounds(
  value: number,
  filterMin: number | null,
  filterMax: number | null,
): boolean {
  if (filterMin !== null && value < filterMin) return false;
  if (filterMax !== null && value > filterMax) return false;
  return true;
}

function bedsPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.minBeds === null && filters.maxBeds === null) return true;
  if (row.group === null) return true;
  return scalarInBounds(row.group.beds, filters.minBeds, filters.maxBeds);
}

function bathsPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.minBaths === null && filters.maxBaths === null) return true;
  if (row.group === null) return true;
  return scalarInBounds(row.group.baths, filters.minBaths, filters.maxBaths);
}

function cityPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.cities.length === 0) return true;
  const label = propertyLocationLabel(row.listing.property);
  return filters.cities.some((token) => cityFilterMatches(row.listing.property, token, label));
}

function statusPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.statuses.length === 0) return true;
  const status = row.state?.interest_status ?? "undecided";
  return filters.statuses.includes(status);
}

function visitedPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  return filters.visited === null || (row.state?.visited ?? false) === filters.visited;
}

function availabilityPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  return filters.availabilities.length === 0 || filters.availabilities.includes(rowAvailability(row));
}

// Effective criterion value for the plan this row displays, read from the
// persisted breakdown (§9.3) — the only per-criterion data the Overview loads.
// A criterion absent from the rubric (or an unscored row) reads as unknown.
export function criterionValue(row: OverviewRow, key: string): unknown {
  const entry = row.group?.displayScore?.breakdown.criteria.find((c) => c.key === key);
  if (!entry || entry.unknown) return null;
  return entry.value ?? null;
}

// Enum criterion filters share one shape: empty selection or unknown value
// passes (a pending/disabled criterion is not a verdict), otherwise the value
// must be selected.
function enumCriterionPredicate(
  filterKey: "laundry" | "parking" | "pets" | "cooling",
  criterionKey: string,
): RowPredicate {
  return (row, filters) => {
    const selected = filters[filterKey];
    if (selected.length === 0) return true;
    const value = criterionValue(row, criterionKey);
    if (typeof value !== "string") return true;
    return selected.includes(value);
  };
}

function dishwasherPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.dishwasher === null) return true;
  const value = criterionValue(row, "dishwasher");
  if (typeof value !== "boolean") return true;
  return value === filters.dishwasher;
}

function maxAllInPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.maxAllIn === null) return true;
  const value = allInValue(row);
  if (value === null) return true;
  return value <= filters.maxAllIn;
}

function availableByPredicate(row: OverviewRow, filters: OverviewFilterState): boolean {
  if (filters.availableBy === null || row.group === null) return true;
  const dates = row.group.plans
    .map((plan) => plan.availability_date)
    .filter((d): d is string => d !== null);
  if (dates.length === 0) return true;
  // ISO dates compare lexicographically; earliest available plan decides.
  return dates.some((d) => d <= filters.availableBy!);
}

type RowPredicate = (row: OverviewRow, filters: OverviewFilterState) => boolean;

// Registry — adding a future filter appends one predicate here.
const FILTER_PREDICATES: RowPredicate[] = [
  queryPredicate,
  scorePredicate,
  rentPredicate,
  sqftPredicate,
  bedsPredicate,
  bathsPredicate,
  cityPredicate,
  statusPredicate,
  visitedPredicate,
  availabilityPredicate,
  enumCriterionPredicate("laundry", "in_unit_laundry"),
  enumCriterionPredicate("parking", "parking"),
  enumCriterionPredicate("pets", "pets_policy"),
  enumCriterionPredicate("cooling", "cooling"),
  dishwasherPredicate,
  maxAllInPredicate,
  availableByPredicate,
];

export function applyOverviewFilters(
  rows: OverviewRow[],
  filters: OverviewFilterState,
): OverviewRow[] {
  return rows.filter((row) => FILTER_PREDICATES.every((pred) => pred(row, filters)));
}

export type FilterPillKey = keyof OverviewFilterState;

export interface FilterPill {
  key: FilterPillKey;
  label: string;
}

/** Labels for active filter Pills. One pill per non-null bound. */
export function filterPills(filters: OverviewFilterState): FilterPill[] {
  const pills: FilterPill[] = [];
  if (filters.query !== null && filters.query.trim() !== "") {
    pills.push({ key: "query", label: `Search: ${filters.query.trim()}` });
  }
  if (filters.minScore !== null) {
    pills.push({ key: "minScore", label: `Score ≥ ${filters.minScore}` });
  }
  if (filters.maxScore !== null) {
    pills.push({ key: "maxScore", label: `Score ≤ ${filters.maxScore}` });
  }
  if (filters.minRent !== null) {
    pills.push({ key: "minRent", label: `Rent ≥ $${filters.minRent.toLocaleString()}` });
  }
  if (filters.maxRent !== null) {
    pills.push({ key: "maxRent", label: `Rent ≤ $${filters.maxRent.toLocaleString()}` });
  }
  if (filters.minSqft !== null) {
    pills.push({ key: "minSqft", label: `Sqft ≥ ${filters.minSqft.toLocaleString()}` });
  }
  if (filters.maxSqft !== null) {
    pills.push({ key: "maxSqft", label: `Sqft ≤ ${filters.maxSqft.toLocaleString()}` });
  }
  if (filters.minBeds !== null) {
    pills.push({ key: "minBeds", label: `Beds ≥ ${filters.minBeds}` });
  }
  if (filters.maxBeds !== null) {
    pills.push({ key: "maxBeds", label: `Beds ≤ ${filters.maxBeds}` });
  }
  if (filters.minBaths !== null) {
    pills.push({ key: "minBaths", label: `Baths ≥ ${filters.minBaths}` });
  }
  if (filters.maxBaths !== null) {
    pills.push({ key: "maxBaths", label: `Baths ≤ ${filters.maxBaths}` });
  }
  for (const city of filters.cities) pills.push({ key: "cities", label: `City: ${city}` });
  for (const status of filters.statuses) {
    pills.push({ key: "statuses", label: `Status: ${status.replaceAll("_", " ")}` });
  }
  if (filters.visited !== null) {
    pills.push({ key: "visited", label: filters.visited ? "Visited" : "Not visited" });
  }
  for (const availability of filters.availabilities) {
    pills.push({ key: "availabilities", label: `Availability: ${availability}` });
  }
  const enumPill = (key: FilterPillKey, prefix: string, values: string[]) => {
    for (const value of values) {
      pills.push({ key, label: `${prefix}: ${value.replaceAll("_", " ")}` });
    }
  };
  enumPill("laundry", "Laundry", filters.laundry);
  enumPill("parking", "Parking", filters.parking);
  enumPill("pets", "Pets", filters.pets);
  enumPill("cooling", "Cooling", filters.cooling);
  if (filters.dishwasher !== null) {
    pills.push({ key: "dishwasher", label: filters.dishwasher ? "Dishwasher" : "No dishwasher" });
  }
  if (filters.maxAllIn !== null) {
    pills.push({ key: "maxAllIn", label: `All-in ≤ $${filters.maxAllIn.toLocaleString()}` });
  }
  if (filters.availableBy !== null) {
    pills.push({ key: "availableBy", label: `Available by ${filters.availableBy}` });
  }
  return pills;
}

export type SortKey = "score" | "rent" | "name" | "allIn" | "available" | "added";

export interface SortState {
  key: SortKey;
  dir: "asc" | "desc";
}

/** Earliest availability date (ISO) across the group's plans, or null. */
export function earliestAvailability(row: OverviewRow): string | null {
  const dates = (row.group?.plans ?? [])
    .map((plan) => plan.availability_date)
    .filter((d): d is string => d !== null)
    .sort();
  return dates[0] ?? null;
}

function sortValue(row: OverviewRow, key: SortKey): number | string | null {
  // Listing-level rows (no group) have no score or rent — they sink to the
  // bottom via the null handling in `sortRows`, never coerced to 0.
  if (key === "score") return row.group?.displayScore?.total ?? null;
  if (key === "rent") return row.group ? (row.group.rentMin ?? row.group.rentMax) : null;
  if (key === "allIn") return allInValue(row);
  // ISO dates and timestamps sort correctly as strings.
  if (key === "available") return earliestAvailability(row);
  if (key === "added") return row.listing.created_at;
  return row.listing.property.name.toLowerCase();
}

export function sortRows(rows: OverviewRow[], sort: SortState): OverviewRow[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = sortValue(a, sort.key);
    const vb = sortValue(b, sort.key);
    // Unknowns sink to the bottom regardless of direction.
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    if (va < vb) return -dir;
    if (va > vb) return dir;
    return 0;
  });
}

// Effective all-in monthly cost: read from the persisted per-plan composition
// (never recomputed client-side), so the figure tracks the plan this row
// displays even when the all_in_monthly rubric criterion is disabled. Rows
// scored before scores.all_in_components landed fall back to the breakdown
// criterion (pre-P3-9 interim: advertised rent).
export function allInValue(row: OverviewRow): number | null {
  const composed = row.group?.displayScore?.all_in_components?.total;
  if (typeof composed === "number") return composed;
  const criteria = row.group?.displayScore?.breakdown.criteria ?? [];
  const value = criteria.find((c) => c.key === "all_in_monthly")?.value;
  return typeof value === "number" ? value : null;
}

// The composition detail for a row: the displayed plan's own (per-score,
// P3-9 follow-up), falling back to the listing-level display-plan blob for
// rows whose scores predate the per-plan column.
export function rowComposition(row: OverviewRow): AllInComponents | null {
  return row.group?.displayScore?.all_in_components ?? row.listing.all_in_components;
}

export function formatRange(min: number | null, max: number | null, prefix = ""): string {
  if (min === null && max === null) return "—";
  if (min !== null && max !== null && min !== max) {
    return `${prefix}${min.toLocaleString()}–${prefix}${max.toLocaleString()}`;
  }
  const value = (min ?? max) as number;
  return `${prefix}${value.toLocaleString()}`;
}
