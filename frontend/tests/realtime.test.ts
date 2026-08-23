import { describe, expect, it } from "vitest";

import { invalidationKeysForRealtime } from "../src/lib/realtime";

describe("Realtime invalidation map", () => {
  const huntId = "hunt-1";

  it.each([
    ["hunt_members", [["hunt_members", huntId], ["hunt_contributors", huntId], ["hunts"]]],
    ["hunt_listings", [["hunt_listings", huntId], ["extractions"]]],
    ["scores", [["hunt_listings", huntId], ["extractions"]]],
    ["comments", [["comments"], ["hunt_listings", huntId]]],
    ["ratings", [["ratings"]]],
    ["listing_unit_group_states", [["listing_unit_group_states", huntId]]],
    ["hunt_listing_refresh_status", [["hunt_listing_refresh_status", huntId]]],
    ["jobs", [["jobs", huntId], ["attention", huntId]]],
    ["job_events", [["jobs", huntId], ["attention", huntId]]],
    // Visit families invalidate broadly: the rows below `visits` carry no
    // hunt_id, and the writer may be on a different Visit than the reader.
    ["visits", [["visits", huntId], ["visit"], ["visit_unit_group_scores", huntId]]],
    ["visit_units", [["visits", huntId], ["visit"], ["visit_unit_group_scores", huntId]]],
    // An answer arriving can open or close a fork, and the conflicts view is
    // derived from this table with no feed of its own (VC-6).
    [
      "visit_entries",
      [["visit_entries"], ["visit_entry_conflicts"], ["visit_unit_group_scores", huntId]],
    ],
    ["visit_defects", [["visit_defects"]]],
    ["visit_custom_items", [["visit_custom_items"]]],
  ] as const)("maps %s events", (table, expected) => {
    expect(invalidationKeysForRealtime(table, huntId)).toEqual(expected);
  });
});
