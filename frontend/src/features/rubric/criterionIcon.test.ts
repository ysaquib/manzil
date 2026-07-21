import { describe, expect, it } from "vitest";
import { IconBed, IconHome, IconListCheck } from "@tabler/icons-react";

import { criterionIconFor } from "./criterionIcon";

describe("criterionIconFor", () => {
  it("resolves a specific icon for a known catalog key", () => {
    expect(criterionIconFor({ key: "beds", category: "unit" })).toBe(IconBed);
  });

  it("falls back to the category icon for an unknown key", () => {
    // Unknown key, known category -> category fallback (unit -> IconHome).
    expect(criterionIconFor({ key: "custom_thing", category: "unit" })).toBe(IconHome);
  });

  it("falls back to a generic icon for an unknown key and category", () => {
    expect(criterionIconFor({ key: "custom_thing", category: "unknown" })).toBe(IconListCheck);
  });
});
