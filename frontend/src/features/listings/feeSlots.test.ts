import { describe, expect, it } from "vitest";

import { FEE_SLOTS } from "./types";

describe("FEE_SLOTS", () => {
  it("includes the §9.5 species-specific pet-rent slots with labels", () => {
    const bySlot = new Map(FEE_SLOTS.map(({ slot, label }) => [slot, label]));
    expect(bySlot.get("pet_rent_cat")).toBe("Pet rent (cat)");
    expect(bySlot.get("pet_rent_dog")).toBe("Pet rent (dog)");
    // The generic pet_rent slot stays alongside the species-specific ones.
    expect(bySlot.get("pet_rent")).toBe("Pet rent");
  });
});
