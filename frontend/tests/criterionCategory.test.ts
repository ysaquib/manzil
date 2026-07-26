import { describe, expect, it } from "vitest";

import { categoryColor } from "../src/features/rubric/criterionCategory";

const CATEGORIES = [
  "unit",
  "cost",
  "tenancy",
  "location",
  "fittings",
  "amenities",
  "management",
];

describe("categoryColor", () => {
  it("returns a Mantine palette name, never a hex value", () => {
    for (const category of CATEGORIES) {
      expect(categoryColor(category)).toMatch(/^[a-z]+$/);
    }
  });

  it("gives every catalog category its own hue", () => {
    const hues = CATEGORIES.map(categoryColor);
    expect(new Set(hues).size).toBe(CATEGORIES.length);
  });

  it("reserves grape and red for meaning, so no category can claim them", () => {
    // grape = human-entered, red = danger / gate firings (UI_DESIGN §4).
    const hues = CATEGORIES.map(categoryColor);
    expect(hues).not.toContain("grape");
    expect(hues).not.toContain("red");
  });

  it("falls back to the warm neutral for an unknown category", () => {
    expect(categoryColor("something_new")).toBe("gray");
  });
});
