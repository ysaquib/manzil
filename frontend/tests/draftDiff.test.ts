import { describe, expect, it } from "vitest";

import {
  changedFeeSlots,
  isDraftDirty,
  isFeeSlotDirty,
  isPinsDirty,
  pinsEqual,
} from "../src/features/listings/draftDiff";
import type { FeeEntry } from "../src/features/listings/types";

const serverFees: FeeEntry[] = [
  {
    hunt_listing_id: "listing-1",
    fee_slot: "admin",
    amount: 50,
    value_state: "extracted",
    entered_by: null,
    evidence_ref: null,
    updated_at: null,
  },
];

describe("listingDetailDraft helpers", () => {
  it("pinsEqual treats matching keys as equal", () => {
    expect(pinsEqual({ "2-2": "a" }, { "2-2": "a" })).toBe(true);
    expect(pinsEqual({}, {})).toBe(true);
  });

  it("isPinsDirty detects pin changes and reverts", () => {
    const baseline = { "2-2": "plan-a" };
    expect(isPinsDirty(baseline, { "2-2": "plan-b" })).toBe(true);
    expect(isPinsDirty(baseline, { "2-2": "plan-a" })).toBe(false);
    expect(isPinsDirty(baseline, {})).toBe(true);
  });

  it("isFeeSlotDirty when draft differs from server or slot is new", () => {
    expect(isFeeSlotDirty("admin", { amount: 75 }, serverFees)).toBe(true);
    expect(isFeeSlotDirty("admin", { amount: 50 }, serverFees)).toBe(false);
    expect(isFeeSlotDirty("parking", { amount: 100 }, serverFees)).toBe(true);
  });

  it("an explicit revert state is dirty even at the same amount", () => {
    const manualFees: FeeEntry[] = [
      { ...serverFees[0], value_state: "manual", entered_by: "u1" },
    ];
    // Reverting a manual 50 to extracted 50 changes only the state — still a save.
    expect(isFeeSlotDirty("admin", { amount: 50, state: "extracted" }, manualFees)).toBe(true);
    // Same amount, no explicit state → untouched, as before.
    expect(isFeeSlotDirty("admin", { amount: 50 }, manualFees)).toBe(false);
    // A no-op revert (state already extracted) stays clean.
    expect(isFeeSlotDirty("admin", { amount: 50, state: "extracted" }, serverFees)).toBe(false);
  });

  it("changedFeeSlots lists only dirty slots", () => {
    const draft = new Map([
      ["admin", { amount: 50 }],
      ["parking", { amount: 25 }],
    ]);
    expect(changedFeeSlots(draft, serverFees)).toEqual(["parking"]);
  });

  it("isDraftDirty for overrides and combined state", () => {
    const baseline = { "2-2": "a" };
    const draft = { "2-2": "a" };
    const overrides = new Map([["beds", { value: 3, note: null }]]);
    expect(isDraftDirty(baseline, draft, overrides, new Map(), serverFees)).toBe(true);
    expect(isDraftDirty(baseline, draft, new Map(), new Map(), serverFees)).toBe(false);
  });
});
