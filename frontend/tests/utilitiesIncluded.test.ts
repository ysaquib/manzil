// §9.5: the effective inclusion list — extracted facts plus active per-utility
// decisions, with a null current override behaving as the revert tombstone it
// is. Pure, so it needs no DOM.
import { describe, expect, it } from "vitest";

import type { DraftUtility } from "../src/features/listings/draftDiff";
import type { UtilityName, UtilityOverride } from "../src/features/listings/types";
import { effectiveUtilitiesIncluded } from "../src/features/listings/utilitiesIncluded";

function override(
  utility: UtilityName,
  included: boolean | null,
  monthly_amount: number | null = null,
): UtilityOverride {
  return {
    id: `o-${utility}`,
    hunt_listing_id: "listing-1",
    utility,
    included,
    monthly_amount,
    user_id: "user-1",
    note: null,
    created_at: "2026-07-28T00:00:00Z",
  };
}

describe("effectiveUtilitiesIncluded", () => {
  it("returns the extracted list when nobody has decided anything", () => {
    expect(effectiveUtilitiesIncluded(["water", "trash"], [])).toEqual(["trash", "water"]);
  });

  it("treats a missing extraction as nothing included", () => {
    expect(effectiveUtilitiesIncluded(null, [])).toEqual([]);
  });

  it("adds and removes utilities per human decisions", () => {
    expect(
      effectiveUtilitiesIncluded(["water"], [override("electric", true), override("water", false)]),
    ).toEqual(["electric"]);
  });

  it("lets a null override fall back to the extracted fact", () => {
    expect(effectiveUtilitiesIncluded(["water"], [override("water", null)])).toEqual(["water"]);
  });

  it("lets an unsaved draft win over the saved decision", () => {
    const drafts = new Map<UtilityName, DraftUtility>([
      ["water", { included: false, monthly_amount: null, note: null }],
    ]);
    expect(effectiveUtilitiesIncluded(["water"], [override("water", true)], drafts)).toEqual([]);
  });
});
