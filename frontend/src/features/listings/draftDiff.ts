// Pure draft diff helpers for the listing detail drawer — unit-testable without
// mounting React context.
import type { FeeEntry, UtilityName, UtilityOverride } from "./types";

export interface DraftOverride {
  value: unknown;
  note: string | null;
  target_scope?: "property" | "floor_plan";
  floor_plan_id?: string | null;
  applicability?: "specific_floor_plans" | "all_units" | null;
}

export interface DraftFee {
  amount: number | null;
  /** target value_state on save; undefined means "manual" (a hand edit).
   * Revert sets "extracted" (restore the machine amount) or "unknown". */
  state?: "manual" | "extracted" | "unknown";
  // P3-SC8 per-charge decisions (§9.5). `null` clears the decision back to the
  // machine default; `undefined` leaves whatever the server holds untouched.
  counted?: boolean | null;
  required?: boolean | null;
  refundable?: boolean | null;
  credited_amount?: number | null;
}

export interface DraftUtility {
  included: boolean | null;
  monthly_amount: number | null;
  note: string | null;
}

export function pinsEqual(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) {
    if ((a[key] ?? undefined) !== (b[key] ?? undefined)) return false;
  }
  return true;
}

export function isPinsDirty(
  baselinePins: Record<string, string>,
  draftPins: Record<string, string>,
): boolean {
  return !pinsEqual(baselinePins, draftPins);
}

export function hasDraftOverrides(draftOverrides: Map<string, DraftOverride>): boolean {
  return draftOverrides.size > 0;
}

export function isFeeSlotDirty(
  slot: string,
  draft: DraftFee | undefined,
  serverFees: FeeEntry[],
): boolean {
  if (!draft) return false;
  const server = serverFees.find((f) => f.fee_slot === slot);
  if (server?.amount !== draft.amount) return true;
  // A decision change is a change even when the amount is untouched: unticking
  // "count toward all-in" alters the scored figure without moving a dollar.
  for (const key of ["counted", "required", "refundable", "credited_amount"] as const) {
    if (draft[key] !== undefined && draft[key] !== (server?.[key] ?? null)) return true;
  }
  // An explicit target state (revert) is a change even at the same amount.
  return draft.state !== undefined && draft.state !== (server?.value_state ?? "unknown");
}

export function isFeesDirty(
  draftFees: Map<string, DraftFee>,
  serverFees: FeeEntry[],
): boolean {
  for (const [slot, draft] of draftFees) {
    if (isFeeSlotDirty(slot, draft, serverFees)) return true;
  }
  return false;
}

export function isUtilityDirty(
  utility: UtilityName,
  draft: DraftUtility | undefined,
  serverUtilities: UtilityOverride[],
): boolean {
  if (!draft) return false;
  const server = serverUtilities.find((entry) => entry.utility === utility);
  return (
    draft.included !== (server?.included ?? undefined) ||
    draft.monthly_amount !== (server?.monthly_amount ?? null) ||
    draft.note !== (server?.note ?? null)
  );
}

export function changedUtilities(
  draftUtilities: Map<UtilityName, DraftUtility>,
  serverUtilities: UtilityOverride[],
): UtilityName[] {
  return [...draftUtilities.keys()].filter((utility) =>
    isUtilityDirty(utility, draftUtilities.get(utility), serverUtilities),
  );
}

export function isDraftDirty(
  baselinePins: Record<string, string>,
  draftPins: Record<string, string>,
  draftOverrides: Map<string, DraftOverride>,
  draftFees: Map<string, DraftFee>,
  serverFees: FeeEntry[],
  draftUtilities: Map<UtilityName, DraftUtility> = new Map(),
  serverUtilities: UtilityOverride[] = [],
): boolean {
  return (
    isPinsDirty(baselinePins, draftPins) ||
    hasDraftOverrides(draftOverrides) ||
    isFeesDirty(draftFees, serverFees) ||
    changedUtilities(draftUtilities, serverUtilities).length > 0
  );
}

export function changedFeeSlots(
  draftFees: Map<string, DraftFee>,
  serverFees: FeeEntry[],
): string[] {
  const slots: string[] = [];
  for (const [slot, draft] of draftFees) {
    if (isFeeSlotDirty(slot, draft, serverFees)) slots.push(slot);
  }
  return slots;
}
