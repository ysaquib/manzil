import { describe, expect, it } from "vitest";

import { invalidationKeysForRealtime } from "../src/lib/realtime";

describe("Realtime invalidation map", () => {
  const huntId = "hunt-1";

  it.each([
    ["hunt_listings", [["hunt_listings", huntId]]],
    ["scores", [["hunt_listings", huntId]]],
    ["comments", [["comments"], ["hunt_listings", huntId]]],
    ["ratings", [["ratings"]]],
    ["listing_unit_group_states", [["listing_unit_group_states", huntId]]],
    ["jobs", [["jobs", huntId]]],
    ["job_events", [["jobs", huntId]]],
  ] as const)("maps %s events", (table, expected) => {
    expect(invalidationKeysForRealtime(table, huntId)).toEqual(expected);
  });
});
