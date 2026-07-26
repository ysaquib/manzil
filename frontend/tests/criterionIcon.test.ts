import { describe, expect, it } from "vitest";
import { IconBed, IconBuildingCommunity, IconHome, IconListCheck } from "@tabler/icons-react";

import { criterionIconFor } from "../src/features/rubric/criterionIcon";

// Every key seeded in criteria_catalog. A key missing from BY_KEY silently
// falls through to its category icon, which is how twelve Property criteria all
// ended up rendering the same house (UI Decision Log 2026-07-25).
const SEEDED_KEYS = [
  ["clubhouse", "amenities"],
  ["emergency_maintenance", "management"],
  ["fitness_center", "amenities"],
  ["internet_readiness", "amenities"],
  ["maintenance_on_site", "management"],
  ["management_on_site", "management"],
  ["online_maintenance_requests", "management"],
  ["online_payments", "management"],
  ["package_handling", "amenities"],
  ["pool", "amenities"],
  ["property_types", "amenities"],
  ["smoking_policy", "tenancy"],
  ["baths", "unit"],
  ["beds", "unit"],
  ["cooling", "fittings"],
  ["dishwasher", "fittings"],
  ["in_unit_laundry", "fittings"],
  ["parking", "unit"],
  ["patio_balcony", "unit"],
  ["private_entry", "unit"],
  ["sqft", "unit"],
  ["unit_types", "unit"],
  ["min_lease_months", "tenancy"],
  ["pets_policy", "tenancy"],
  ["all_in_monthly", "cost"],
  ["security_deposit", "cost"],
  ["availability_date", "tenancy"],
  ["flooring_quality", "fittings"],
  ["kitchen_quality", "fittings"],
  ["grocery_proximity", "location"],
  ["location_safety", "location"],
  ["management_reviews", "management"],
] as const;

describe("criterionIconFor", () => {
  it("resolves a specific icon for a known catalog key", () => {
    expect(criterionIconFor({ key: "beds", category: "unit" })).toBe(IconBed);
  });

  it("gives every seeded catalog key a distinct icon", () => {
    const icons = SEEDED_KEYS.map(([key, category]) => criterionIconFor({ key, category }));
    expect(new Set(icons).size).toBe(SEEDED_KEYS.length);
  });

  it("never leaves a seeded key on its category fallback", () => {
    for (const [key, category] of SEEDED_KEYS) {
      const specific = criterionIconFor({ key, category });
      const fallback = criterionIconFor({ key: "unmapped_key", category });
      expect(specific, `${key} falls through to the ${category} fallback`).not.toBe(fallback);
    }
  });

  it("falls back to the category icon for an unknown key", () => {
    expect(criterionIconFor({ key: "custom_thing", category: "unit" })).toBe(IconHome);
    expect(criterionIconFor({ key: "custom_thing", category: "amenities" })).toBe(
      IconBuildingCommunity,
    );
  });

  it("falls back to a generic icon for an unknown key and category", () => {
    expect(criterionIconFor({ key: "custom_thing", category: "unknown" })).toBe(IconListCheck);
  });
});
