// Drawer-level draft state (pins, overrides, fees): batch edits locally, save
// once. Provider is keyed by listing.id so switching listings remounts cleanly.
import { notifications } from "@mantine/notifications";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../../lib/apiClient";
import {
  changedFeeSlots,
  changedUtilities,
  isDraftDirty,
  isPinsDirty,
  type DraftFee,
  type DraftOverride,
  type DraftUtility,
} from "./draftDiff";
import { useCreateOverride, usePatchPins, useUpsertFee, useUpsertUtilityOverride } from "./api";
import type { FeeEntry, Listing, UtilityName, UtilityOverride } from "./types";

interface ListingDetailDraftContextValue {
  draftPins: Record<string, string>;
  draftOverrides: Map<string, DraftOverride>;
  draftFees: Map<string, DraftFee>;
  draftUtilities: Map<UtilityName, DraftUtility>;
  isDirty: boolean;
  saving: boolean;
  setDraftPin: (groupKey: string, planId: string | null) => void;
  setDraftOverride: (criterionKey: string, entry: DraftOverride) => void;
  clearDraftOverride: (criterionKey: string) => void;
  setDraftFee: (slot: string, entry: DraftFee) => void;
  clearDraftFee: (slot: string) => void;
  setDraftUtility: (utility: UtilityName, entry: DraftUtility) => void;
  clearDraftUtility: (utility: UtilityName) => void;
  resetDraft: () => void;
  saveAll: () => Promise<boolean>;
}

const ListingDetailDraftContext = createContext<ListingDetailDraftContextValue | null>(null);

export function useListingDetailDraft(): ListingDetailDraftContextValue {
  const ctx = useContext(ListingDetailDraftContext);
  if (!ctx) {
    throw new Error("useListingDetailDraft must be used within ListingDetailDraftProvider");
  }
  return ctx;
}

export function ListingDetailDraftProvider({
  huntId,
  listing,
  serverFees,
  serverUtilityOverrides = [],
  children,
}: {
  huntId: string;
  listing: Listing;
  serverFees: FeeEntry[];
  serverUtilityOverrides?: UtilityOverride[];
  children: ReactNode;
}) {
  const [baselinePins, setBaselinePins] = useState<Record<string, string>>(
    () => ({ ...(listing.pins ?? {}) }),
  );
  const [draftPins, setDraftPins] = useState<Record<string, string>>(
    () => ({ ...(listing.pins ?? {}) }),
  );
  const [draftOverrides, setDraftOverrides] = useState<Map<string, DraftOverride>>(
    () => new Map(),
  );
  const [draftFees, setDraftFees] = useState<Map<string, DraftFee>>(() => new Map());
  const [draftUtilities, setDraftUtilities] = useState<Map<UtilityName, DraftUtility>>(
    () => new Map(),
  );
  const [saving, setSaving] = useState(false);

  const patchPins = usePatchPins(huntId);
  const createOverride = useCreateOverride(huntId, listing.id);
  const upsertFee = useUpsertFee(huntId, listing.id);
  const upsertUtility = useUpsertUtilityOverride(huntId, listing.id);

  const isDirty = useMemo(
    () => isDraftDirty(
      baselinePins, draftPins, draftOverrides, draftFees, serverFees, draftUtilities, serverUtilityOverrides,
    ),
    [baselinePins, draftPins, draftOverrides, draftFees, serverFees, draftUtilities, serverUtilityOverrides],
  );

  const setDraftPin = useCallback((groupKey: string, planId: string | null) => {
    setDraftPins((prev) => {
      const next = { ...prev };
      if (planId === null) delete next[groupKey];
      else next[groupKey] = planId;
      return next;
    });
  }, []);

  const setDraftOverride = useCallback((criterionKey: string, entry: DraftOverride) => {
    setDraftOverrides((prev) => {
      const next = new Map(prev);
      next.set(criterionKey, entry);
      return next;
    });
  }, []);

  const clearDraftOverride = useCallback((criterionKey: string) => {
    setDraftOverrides((prev) => {
      if (!prev.has(criterionKey)) return prev;
      const next = new Map(prev);
      next.delete(criterionKey);
      return next;
    });
  }, []);

  const setDraftFee = useCallback((slot: string, entry: DraftFee) => {
    setDraftFees((prev) => {
      const next = new Map(prev);
      next.set(slot, entry);
      return next;
    });
  }, []);

  const clearDraftFee = useCallback((slot: string) => {
    setDraftFees((prev) => {
      if (!prev.has(slot)) return prev;
      const next = new Map(prev);
      next.delete(slot);
      return next;
    });
  }, []);

  const setDraftUtility = useCallback((utility: UtilityName, entry: DraftUtility) => {
    setDraftUtilities((prev) => new Map(prev).set(utility, entry));
  }, []);

  const clearDraftUtility = useCallback((utility: UtilityName) => {
    setDraftUtilities((prev) => {
      if (!prev.has(utility)) return prev;
      const next = new Map(prev);
      next.delete(utility);
      return next;
    });
  }, []);

  const resetDraft = useCallback(() => {
    setDraftPins({ ...baselinePins });
    setDraftOverrides(new Map());
    setDraftFees(new Map());
    setDraftUtilities(new Map());
  }, [baselinePins]);

  const saveAll = useCallback(async (): Promise<boolean> => {
    if (!isDirty) return true;

    setSaving(true);
    const pinsChanged = isPinsDirty(baselinePins, draftPins);
    const overrideEntries = [...draftOverrides.entries()];
    const feeSlots = changedFeeSlots(draftFees, serverFees);
    const utilities = changedUtilities(draftUtilities, serverUtilityOverrides);

    type Task =
      | { kind: "pins" }
      | { kind: "override"; key: string; entry: DraftOverride }
      | {
          kind: "fee";
          slot: string;
          amount: number | null;
          state: "manual" | "extracted" | "unknown";
          decisions: Pick<DraftFee, "counted" | "required" | "refundable" | "credited_amount">;
        }
      | { kind: "utility"; utility: UtilityName; entry: DraftUtility };

    const tasks: Task[] = [];
    if (pinsChanged) tasks.push({ kind: "pins" });
    for (const [key, entry] of overrideEntries) tasks.push({ kind: "override", key, entry });
    for (const slot of feeSlots) {
      const draft = draftFees.get(slot);
      tasks.push({
        kind: "fee",
        slot,
        amount: draft?.amount ?? null,
        state: draft?.state ?? "manual",
        decisions: {
          counted: draft?.counted,
          required: draft?.required,
          refundable: draft?.refundable,
          credited_amount: draft?.credited_amount,
        },
      });
    }
    for (const utility of utilities) {
      const entry = draftUtilities.get(utility);
      if (entry) tasks.push({ kind: "utility", utility, entry });
    }

    const results = await Promise.allSettled(
      tasks.map((task) => {
        if (task.kind === "pins") {
          return patchPins.mutateAsync({ listingId: listing.id, pins: draftPins });
        }
        if (task.kind === "override") {
          return createOverride.mutateAsync({
            criterion_key: task.key,
            value: task.entry.value,
            note: task.entry.note,
            target_scope: task.entry.target_scope ?? "property",
            floor_plan_id: task.entry.floor_plan_id ?? null,
            applicability: task.entry.applicability ?? null,
          });
        }
        if (task.kind === "utility") {
          return upsertUtility.mutateAsync({
            utility: task.utility,
            included: task.entry.included,
            monthly_amount: task.entry.monthly_amount,
            note: task.entry.note,
          });
        }
        return upsertFee.mutateAsync({
          slot: task.slot,
          amount: task.amount,
          value_state: task.state,
          ...task.decisions,
        });
      }),
    );

    const failed: string[] = [];
    const succeededOverrides = new Set<string>();
    const succeededFees = new Set<string>();
    const succeededUtilities = new Set<UtilityName>();

    results.forEach((result, i) => {
      const task = tasks[i];
      if (result.status === "fulfilled") {
        if (task.kind === "override") succeededOverrides.add(task.key);
        if (task.kind === "fee") succeededFees.add(task.slot);
        if (task.kind === "utility") succeededUtilities.add(task.utility);
        return;
      }
      if (task.kind === "pins") failed.push("floor plan pin");
      else if (task.kind === "override") failed.push(`override (${task.key})`);
      else if (task.kind === "utility") failed.push(`utility (${task.utility})`);
      else failed.push(`fee (${task.slot})`);
    });

    const pinsSucceeded = !pinsChanged || results.some((r, i) => tasks[i].kind === "pins" && r.status === "fulfilled");

    if (pinsSucceeded && pinsChanged) {
      setBaselinePins({ ...draftPins });
    }

    if (succeededOverrides.size > 0) {
      setDraftOverrides((prev) => {
        const next = new Map(prev);
        for (const key of succeededOverrides) next.delete(key);
        return next;
      });
    }

    if (succeededFees.size > 0) {
      setDraftFees((prev) => {
        const next = new Map(prev);
        for (const slot of succeededFees) next.delete(slot);
        return next;
      });
    }
    if (succeededUtilities.size > 0) {
      setDraftUtilities((prev) => {
        const next = new Map(prev);
        for (const utility of succeededUtilities) next.delete(utility);
        return next;
      });
    }

    setSaving(false);

    if (failed.length === 0) {
      const hadOverrides = overrideEntries.length > 0 || utilities.length > 0;
      notifications.show({
        title: "Changes saved",
        message: hadOverrides
          ? "Re-scoring runs in the background — scores update in a few seconds."
          : "Your edits are saved.",
        color: "green",
      });
      return true;
    }

    notifications.show({
      title: "Couldn't save everything",
      message: `Failed: ${failed.join(", ")}. Unsaved edits are still in the drawer.`,
      color: "red",
    });
    return false;
  }, [
    isDirty,
    baselinePins,
    draftPins,
    draftOverrides,
    draftFees,
    serverFees,
    draftUtilities,
    serverUtilityOverrides,
    patchPins,
    createOverride,
    upsertFee,
    upsertUtility,
    listing.id,
  ]);

  const value = useMemo(
    () => ({
      draftPins,
      draftOverrides,
      draftFees,
      draftUtilities,
      isDirty,
      saving,
      setDraftPin,
      setDraftOverride,
      clearDraftOverride,
      setDraftFee,
      clearDraftFee,
      setDraftUtility,
      clearDraftUtility,
      resetDraft,
      saveAll,
    }),
    [
      draftPins,
      draftOverrides,
      draftFees,
      draftUtilities,
      isDirty,
      saving,
      setDraftPin,
      setDraftOverride,
      clearDraftOverride,
      setDraftFee,
      clearDraftFee,
      setDraftUtility,
      clearDraftUtility,
      resetDraft,
      saveAll,
    ],
  );

  return (
    <ListingDetailDraftContext.Provider value={value}>{children}</ListingDetailDraftContext.Provider>
  );
}

export function formatDraftSaveError(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unexpected error";
}
