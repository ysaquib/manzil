import { describe, expect, it } from "vitest";

import { invalidationKeysForRealtime } from "./realtime";

describe("Realtime invalidation map", () => {
  const huntId = "hunt-1";

  it.each([
    ["hunt_listings", [["hunt_listings", huntId]]],
    ["scores", [["hunt_listings", huntId]]],
    ["comments", [["comments"], ["hunt_listings", huntId]]],
    ["jobs", [["jobs", huntId]]],
    ["job_events", [["jobs", huntId]]],
  ] as const)("maps %s events", (table, expected) => {
    expect(invalidationKeysForRealtime(table, huntId)).toEqual(expected);
  });
});
