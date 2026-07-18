// Override resolution (§9.6, §20 2026-07-18). Pure and unit-tested.
// Overrides are append-only; the LATEST row per criterion wins, and a null
// value is the revert tombstone — "no longer overridden", falling back to the
// extraction. Mirrors the worker's _resolve_effective_values semantics.
import type { Override } from "./types";

export const REVERT_NOTE = "Reverted to original";

/** Latest non-tombstone override per criterion key. `overrides` must be
 * newest-first, which is how useOverrides orders them. */
export function activeOverrides(overrides: Override[]): Map<string, Override> {
  const latest = new Map<string, Override>();
  for (const override of overrides) {
    if (!latest.has(override.criterion_key)) latest.set(override.criterion_key, override);
  }
  for (const [key, override] of latest) {
    if (override.value === null) latest.delete(key);
  }
  return latest;
}
