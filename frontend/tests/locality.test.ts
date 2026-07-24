import { describe, expect, it } from "vitest";

import { cityFilterMatches, propertyLocationLabel } from "../src/features/listings/locality";

describe("propertyLocationLabel", () => {
  it("shows City, ST when both are present", () => {
    expect(propertyLocationLabel({ city: "Detroit", state: "MI", county: null })).toBe(
      "Detroit, MI",
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
  const property = { city: "Detroit", state: "MI", county: "Wayne County" };

  it("matches legacy bare city tokens", () => {
    expect(cityFilterMatches(property, "Detroit")).toBe(true);
    expect(cityFilterMatches(property, "Detroit")).toBe(false);
  });

  it("matches disambiguated City, ST tokens exactly", () => {
    expect(cityFilterMatches(property, "Detroit, MI")).toBe(true);
    expect(cityFilterMatches(property, "Detroit, OH")).toBe(false);
  });
});
