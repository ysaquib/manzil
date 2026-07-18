// §9.5 one-time / move-in fee display logic (§20 2026-07-18). Pure and
// unit-tested. Display-only arithmetic over the `one_time_fees` extraction —
// the scored all-in never includes one-time fees, so nothing here touches
// scoring truth.
import type { OneTimeFee } from "./types";

// Mirrors the worker's slot_for_one_time_fee keyword map (pet_costs.py) so a
// slot row can surface its extracted fee's basis without a round trip.
const SLOT_KEYWORDS: [string, string[]][] = [
  ["application_fee", ["application", "app fee"]],
  ["pet_deposit", ["pet deposit"]],
  ["pet_fee", ["pet fee", "pet charge"]],
  ["admin", ["admin"]],
];

export function slotForOneTimeFee(name: string): string | null {
  const lowered = name.toLowerCase();
  for (const [slot, keywords] of SLOT_KEYWORDS) {
    if (keywords.some((k) => lowered.includes(k))) return slot;
  }
  return null;
}

export function basisLabel(fee: OneTimeFee): string {
  const basis =
    fee.basis === "per_person"
      ? "per person"
      : fee.basis === "per_application"
        ? "per application"
        : fee.basis === "per_pet"
          ? "per pet"
          : "";
  const refund =
    fee.refundable == null ? "" : fee.refundable ? "refundable" : "non-refundable";
  return [basis, refund].filter(Boolean).join(", ");
}

/** The extracted one-time fee backing a checklist slot, if any. */
export function feeForSlot(fees: OneTimeFee[], slot: string): OneTimeFee | undefined {
  return fees.find((fee) => slotForOneTimeFee(fee.name) === slot);
}

/** Parse the `one_time_fees` extraction's jsonb value defensively. */
export function parseOneTimeFees(value: unknown): OneTimeFee[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (fee): fee is OneTimeFee =>
      typeof fee === "object" &&
      fee !== null &&
      typeof (fee as OneTimeFee).amount === "number" &&
      typeof (fee as OneTimeFee).name === "string",
  );
}

export interface Household {
  occupants: number;
  cats: number;
  dogs: number;
}

/** Estimated total move-in fees for THIS household: per_person × occupants,
 * per_pet × (cats + dogs), per_application/flat once. Excludes the security
 * deposit (a floor-plan figure). Null when there is nothing to sum. */
export function moveInEstimate(fees: OneTimeFee[], household: Household): number | null {
  if (fees.length === 0) return null;
  const pets = household.cats + household.dogs;
  const total = fees.reduce((sum, fee) => {
    const multiplier =
      fee.basis === "per_person"
        ? Math.max(household.occupants, 1)
        : fee.basis === "per_pet"
          ? pets
          : 1;
    return sum + fee.amount * multiplier;
  }, 0);
  return Math.round(total * 100) / 100;
}
