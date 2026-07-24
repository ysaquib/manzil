import { describe, expect, it } from "vitest";

import { activeOverrides, extractionForFloorPlan } from "../src/features/listings/overrides";
import type { Extraction, Override } from "../src/features/listings/types";

function row(key: string, value: unknown, created_at: string): Override {
  return {
    id: `${key}-${created_at}`,
    hunt_listing_id: "l1",
    criterion_key: key,
    target_scope: "property",
    floor_plan_id: null,
    applicability: null,
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

  it("uses exact then all-unit then Property override precedence", () => {
    const exact = {
      ...row("beds", 3, "2026-07-18"),
      target_scope: "floor_plan" as const,
      floor_plan_id: "fp-1",
      applicability: "specific_floor_plans" as const,
    };
    const allUnits = {
      ...row("beds", 2, "2026-07-18"),
      applicability: "all_units" as const,
    };
    expect(activeOverrides([exact, allUnits], "fp-1").get("beds")?.value).toBe(3);
    expect(activeOverrides([exact, allUnits], "fp-2").get("beds")?.value).toBe(2);
  });
});

describe("extractionForFloorPlan", () => {
  const base: Extraction = {
    id: "e-1",
    property_id: "p-1",
    hunt_id: null,
    criterion_key: "dishwasher",
    record_kind: "resolved",
    origin_key: "resolution:test",
    target_scope: "property",
    floor_plan_id: null,
    applicability: "unit_scope_unspecified",
    claim_group_id: "cg-1",
    value: "unspecified",
    confidence: "high",
    evidence_quote: null,
    source_id: null,
    model: "fixture",
    resolution_rule: "fixture",
    disputed: false,
    extracted_at: "2026-07-18T00:00:00Z",
  };

  it("prefers exact evidence without leaking it to sibling Floor Plans", () => {
    const exact: Extraction = {
      ...base,
      id: "e-2",
      target_scope: "floor_plan",
      floor_plan_id: "fp-1",
      applicability: "specific_floor_plans",
      value: "exact",
    };
    expect(extractionForFloorPlan([base, exact], "dishwasher", "fp-1")?.value).toBe("exact");
    expect(extractionForFloorPlan([base, exact], "dishwasher", "fp-2")?.value).toBe(
      "unspecified",
    );
  });
});
