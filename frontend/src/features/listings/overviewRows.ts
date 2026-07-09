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

// `hide score < N` (§13.2, §9.3 rationale): declutters gate-zeroed rows
// without deleting the "why we rejected it" record. Unscored rows stay
// visible — pending ingestion is not a verdict.
export function filterRows(rows: OverviewRow[], minScore: number | null): OverviewRow[] {
  if (minScore === null) return rows;
  return rows.filter(
    (row) => row.group?.displayScore == null || row.group.displayScore.total >= minScore,
  );
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
