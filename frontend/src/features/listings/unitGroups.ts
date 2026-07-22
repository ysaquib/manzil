// Unit Group derivation (§3, §9.4): group a listing's floor plans by
// (beds, baths); each plan is scored independently and the group displays the
// best score — unless a per-group pin (§8.2 hunt_listings.pins) switches the
// group to the pinned plan. Pure and unit-tested.
import type { FloorPlan, Listing, Score } from "./types";

export interface UnitGroupRow {
  /** pin key, `"{beds}-{baths}"` (§8.2) */
  key: string;
  beds: number;
  baths: number;
  /** Honest set-union of the types represented by the group's Floor Plans. */
  unitTypes: string[];
  plans: FloorPlan[];
  /** number of plans in this group that have a score */
  scoredPlanCount: number;
  /** the plan whose score the row displays: pinned, else best-scored, else first */
  displayPlan: FloorPlan;
  displayScore: Score | null;
  pinnedPlanId: string | null;
  rentMin: number | null;
  rentMax: number | null;
  sqftMin: number | null;
  sqftMax: number | null;
}

export function unitGroupKey(beds: number, baths: number): string {
  return `${beds}-${baths}`;
}

function rangeMin(values: (number | null)[]): number | null {
  const known = values.filter((v): v is number => v !== null);
  return known.length ? Math.min(...known) : null;
}

function rangeMax(values: (number | null)[]): number | null {
  const known = values.filter((v): v is number => v !== null);
  return known.length ? Math.max(...known) : null;
}

export function deriveUnitGroups(listing: Listing): UnitGroupRow[] {
  const scoreByPlan = new Map<string, Score>();
  for (const score of listing.scores) scoreByPlan.set(score.floor_plan_id, score);

  const groups = new Map<string, FloorPlan[]>();
  for (const plan of listing.property.floor_plans) {
    if (plan.is_current === false) continue;
    const key = unitGroupKey(plan.beds, plan.baths);
    const bucket = groups.get(key);
    if (bucket) bucket.push(plan);
    else groups.set(key, [plan]);
  }

  const rows: UnitGroupRow[] = [];
  for (const [key, plans] of groups) {
    const scored = plans.filter((p) => scoreByPlan.has(p.id));
    const best = scored.length
      ? scored.reduce((a, b) =>
          (scoreByPlan.get(b.id)?.total ?? -Infinity) > (scoreByPlan.get(a.id)?.total ?? -Infinity)
            ? b
            : a,
        )
      : null;

    const pinnedPlanId = listing.pins[key] ?? null;
    const pinned = pinnedPlanId ? (plans.find((p) => p.id === pinnedPlanId) ?? null) : null;
    const displayPlan = pinned ?? best ?? plans[0];
    const displayScore = scoreByPlan.get(displayPlan.id) ?? null;

    rows.push({
      key,
      beds: plans[0].beds,
      baths: plans[0].baths,
      unitTypes: [...new Set(plans.flatMap((plan) => plan.unit_types ?? []))].sort(),
      plans,
      scoredPlanCount: scored.length,
      displayPlan,
      displayScore,
      pinnedPlanId: pinned ? pinnedPlanId : null,
      rentMin: rangeMin(plans.map((p) => p.rent_min ?? p.rent_max)),
      rentMax: rangeMax(plans.map((p) => p.rent_max ?? p.rent_min)),
      sqftMin: rangeMin(plans.map((p) => p.sqft_min ?? p.sqft_max)),
      sqftMax: rangeMax(plans.map((p) => p.sqft_max ?? p.sqft_min)),
    });
  }

  // Larger units first — matches how hunts compare (2bd before 1bd before studio).
  rows.sort((a, b) => b.beds - a.beds || b.baths - a.baths);
  return rows;
}

/** Re-resolve a drawer row from live listings after mutations (e.g. pin patch). */
export function resolveRow(
  listings: Listing[],
  listingId: string,
  groupKey: string | null,
): { listing: Listing | null; group: UnitGroupRow | null } {
  const listing = listings.find((l) => l.id === listingId) ?? null;
  if (!listing) return { listing: null, group: null };
  if (groupKey === null) return { listing, group: null };
  const group = deriveUnitGroups(listing).find((g) => g.key === groupKey) ?? null;
  return { listing, group };
}

/** Overlay draft pins onto a listing for live drawer preview before save. */
export function resolveRowWithDraft(
  listings: Listing[],
  listingId: string,
  groupKey: string | null,
  draftPins: Record<string, string>,
): { listing: Listing | null; group: UnitGroupRow | null } {
  const listing = listings.find((l) => l.id === listingId) ?? null;
  if (!listing) return { listing: null, group: null };
  const listingWithDraft: Listing = { ...listing, pins: draftPins };
  if (groupKey === null) return { listing: listingWithDraft, group: null };
  const group = deriveUnitGroups(listingWithDraft).find((g) => g.key === groupKey) ?? null;
  return { listing: listingWithDraft, group };
}
