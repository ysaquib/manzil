// Overview row building, filtering, sorting (P1-10). Pure and unit-tested;
// the table component stays declarative.
import type { Listing } from "./types";
import { deriveUnitGroups, type UnitGroupRow } from "./unitGroups";

export interface OverviewRow {
  listing: Listing;
  // null → a listing-level row: the listing has no unit groups yet, either
  // because it is still ingesting (pending) or because ingest found no available
  // floor plans (no-availability, §8.2). See `rowAvailability`.
  group: UnitGroupRow | null;
}

export function buildRows(listings: Listing[]): OverviewRow[] {
  return listings.flatMap((listing): OverviewRow[] => {
    const groups = deriveUnitGroups(listing);
    // A listing with no scorable plans still gets exactly one row so it stays
    // visible — dimmed for no-availability, "pending" while it ingests.
    if (groups.length === 0) return [{ listing, group: null }];
    return groups.map((group) => ({ listing, group }));
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
  minRent: number | null;
  maxRent: number | null;
  minSqft: number | null;
  maxSqft: number | null;
}

export const DEFAULT_OVERVIEW_FILTERS: OverviewFilterState = {
  minScore: null,
  minRent: null,
  maxRent: null,
  minSqft: null,
  maxSqft: null,
};

export function hasActiveFilters(filters: OverviewFilterState): boolean {
  return Object.values(filters).some((v) => v !== null);
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
  if (filters.minScore === null) return true;
  if (row.group?.displayScore == null) return true;
  return row.group.displayScore.total >= filters.minScore;
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

type RowPredicate = (row: OverviewRow, filters: OverviewFilterState) => boolean;

// Registry — adding a future filter appends one predicate here.
const FILTER_PREDICATES: RowPredicate[] = [scorePredicate, rentPredicate, sqftPredicate];

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

export function formatRange(min: number | null, max: number | null, prefix = ""): string {
  if (min === null && max === null) return "—";
  if (min !== null && max !== null && min !== max) {
    return `${prefix}${min.toLocaleString()}–${prefix}${max.toLocaleString()}`;
  }
  const value = (min ?? max) as number;
  return `${prefix}${value.toLocaleString()}`;
}
