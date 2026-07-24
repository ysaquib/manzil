import { describe, expect, it } from "vitest";

import { cityFilterMatches, propertyLocationLabel } from "../src/features/listings/locality";

describe("propertyLocationLabel", () => {
  it("shows City, ST when both are present", () => {
    expect(propertyLocationLabel({ city: "Canton", state: "MI", county: null })).toBe(
      "Canton, MI",
    );
  });

  it("falls back to county/state when city is absent", () => {
    expect(
      propertyLocationLabel({ city: null, state: "MI", county: "Wayne County" }),
    ).toBe("Wayne County, MI");
  });

  it("returns Unknown when no locality fields exist", () => {
    expect(propertyLocationLabel({ city: null, state: null, county: null })).toBe("Unknown");
  });
});

describe("cityFilterMatches", () => {
  const property = { city: "Canton", state: "MI", county: "Wayne County" };

  it("matches legacy bare city tokens", () => {
    expect(cityFilterMatches(property, "Canton")).toBe(true);
    expect(cityFilterMatches(property, "Detroit")).toBe(false);
  });

  it("matches disambiguated City, ST tokens exactly", () => {
    expect(cityFilterMatches(property, "Canton, MI")).toBe(true);
    expect(cityFilterMatches(property, "Canton, OH")).toBe(false);
  });
});
