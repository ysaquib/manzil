import { describe, expect, it } from "vitest";

import {
  basisLabel,
  extractedFeeOriginals,
  feeForSlot,
  moveInEstimate,
  parseOneTimeFees,
  slotForOneTimeFee,
} from "../src/features/listings/oneTimeFees";
import type { OneTimeFee } from "../src/features/listings/types";

const FEES: OneTimeFee[] = [
  { name: "application fee", amount: 50, basis: "per_person" },
  { name: "admin fee", amount: 150, basis: "per_application" },
  { name: "pet deposit", amount: 300, basis: "per_pet", refundable: true },
  { name: "elevator reservation", amount: 75, basis: "flat" },
];

describe("slotForOneTimeFee", () => {
  it("mirrors the worker keyword map", () => {
    expect(slotForOneTimeFee("Application Fee")).toBe("application_fee");
    expect(slotForOneTimeFee("Administrative fee")).toBe("admin");
    expect(slotForOneTimeFee("Pet Deposit (refundable)")).toBe("pet_deposit");
    expect(slotForOneTimeFee("Non-refundable pet fee")).toBe("pet_fee");
    expect(slotForOneTimeFee("Elevator reservation")).toBeNull();
  });
});

describe("basisLabel / feeForSlot", () => {
  it("labels basis and refundability, empty for plain flat fees", () => {
    expect(basisLabel(FEES[0])).toBe("per person");
    expect(basisLabel(FEES[2])).toBe("per pet, refundable");
    expect(basisLabel(FEES[3])).toBe("");
  });

  it("resolves the extracted fee backing a slot", () => {
    expect(feeForSlot(FEES, "admin")?.amount).toBe(150);
    expect(feeForSlot(FEES, "pet_fee")).toBeUndefined();
  });
});

describe("moveInEstimate", () => {
  it("scales per_person by occupants and per_pet by the pet count", () => {
    // 50×2 occupants + 150 + 300×1 pet + 75 = 625
    expect(moveInEstimate(FEES, { occupants: 2, cats: 1, dogs: 0 })).toBe(625);
  });

  it("a petless household pays no per-pet fees; empty list is null", () => {
    expect(moveInEstimate(FEES, { occupants: 1, cats: 0, dogs: 0 })).toBe(275);
    expect(moveInEstimate([], { occupants: 2, cats: 1, dogs: 1 })).toBeNull();
  });
});

describe("parseOneTimeFees", () => {
  it("accepts the extraction jsonb shape and rejects junk", () => {
    expect(parseOneTimeFees(FEES)).toHaveLength(4);
    expect(parseOneTimeFees(null)).toEqual([]);
    expect(parseOneTimeFees([{ name: "x" }, "junk", { amount: 5, name: "y" }])).toHaveLength(1);
  });
});

describe("extractedFeeOriginals", () => {
  it("maps mandatory and one-time extractions to their slots", () => {
    const originals = extractedFeeOriginals(
      [
        { name: "valet trash", amount_monthly: 25 },
        { name: "water/sewer billing", amount_monthly: 60 },
        { name: "amenity fee", amount_monthly: 10 }, // no slot → not revertible
      ],
      FEES,
    );
    expect(originals.get("valet_trash")).toBe(25);
    expect(originals.get("water_sewer")).toBe(60);
    expect(originals.get("application_fee")).toBe(50);
    expect(originals.get("admin")).toBe(150);
    expect(originals.get("pet_deposit")).toBe(300);
    expect(originals.has("pet_rent")).toBe(false); // no extraction row for pets
  });

  it("tolerates absent extractions", () => {
    expect(extractedFeeOriginals(undefined, null).size).toBe(0);
  });
});
