import { describe, expect, it } from "vitest";

import { activeOverrides } from "./overrides";
import type { Override } from "./types";

function row(key: string, value: unknown, created_at: string): Override {
  return {
    id: `${key}-${created_at}`,
    hunt_listing_id: "l1",
    criterion_key: key,
    value,
    user_id: "u1",
    note: null,
    created_at,
  };
}

describe("activeOverrides", () => {
  it("keeps the latest row per key (input is newest-first)", () => {
    const map = activeOverrides([
      row("beds", 3, "2026-07-18"),
      row("beds", 2, "2026-07-10"),
      row("sqft", 900, "2026-07-12"),
    ]);
    expect(map.get("beds")?.value).toBe(3);
    expect(map.get("sqft")?.value).toBe(900);
  });

  it("treats a null value as the revert tombstone (§9.6)", () => {
    const map = activeOverrides([
      row("beds", null, "2026-07-18"), // reverted
      row("beds", 2, "2026-07-10"),
      row("all_in_monthly", 1800, "2026-07-17"),
    ]);
    expect(map.has("beds")).toBe(false);
    expect(map.get("all_in_monthly")?.value).toBe(1800);
  });
});
