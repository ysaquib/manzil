// Overview row building, filtering, sorting (P1-10). Pure and unit-tested;
// the table component stays declarative.
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

export interface OverviewFilterState {
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
}

export const DEFAULT_OVERVIEW_FILTERS: OverviewFilterState = {
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
};

export function hasActiveFilters(filters: OverviewFilterState): boolean {
  return Object.values(filters).some((v) => (Array.isArray(v) ? v.length > 0 : v !== null));
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
  return filters.cities.length === 0 || filters.cities.includes(row.listing.property.city ?? "Unknown");
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

type RowPredicate = (row: OverviewRow, filters: OverviewFilterState) => boolean;

// Registry — adding a future filter appends one predicate here.
const FILTER_PREDICATES: RowPredicate[] = [
  scorePredicate,
  rentPredicate,
  sqftPredicate,
  bedsPredicate,
  bathsPredicate,
  cityPredicate,
  statusPredicate,
  visitedPredicate,
  availabilityPredicate,
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
  return pills;
}

export type SortKey = "score" | "rent" | "name";

export interface SortState {
  key: SortKey;
  dir: "asc" | "desc";
}

function sortValue(row: OverviewRow, key: SortKey): number | string | null {
  // Listing-level rows (no group) have no score or rent — they sink to the
  // bottom via the null handling in `sortRows`, never coerced to 0.
  if (key === "score") return row.group?.displayScore?.total ?? null;
  if (key === "rent") return row.group ? (row.group.rentMin ?? row.group.rentMax) : null;
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
