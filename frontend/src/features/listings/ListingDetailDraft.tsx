// Drawer-level draft state (pins, overrides, fees): batch edits locally, save
// once. Provider is keyed by listing.id so switching listings remounts cleanly.
import { notifications } from "@mantine/notifications";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../../lib/apiClient";
import {
  changedFeeSlots,
  isDraftDirty,
  isPinsDirty,
  type DraftFee,
  type DraftOverride,
} from "./draftDiff";
import { useCreateOverride, usePatchPins, useUpsertFee } from "./api";
import type { FeeEntry, Listing } from "./types";

interface ListingDetailDraftContextValue {
  draftPins: Record<string, string>;
  draftOverrides: Map<string, DraftOverride>;
  draftFees: Map<string, DraftFee>;
  isDirty: boolean;
  saving: boolean;
  setDraftPin: (groupKey: string, planId: string | null) => void;
  setDraftOverride: (criterionKey: string, entry: DraftOverride) => void;
  clearDraftOverride: (criterionKey: string) => void;
  setDraftFee: (slot: string, entry: DraftFee) => void;
  clearDraftFee: (slot: string) => void;
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
  children,
}: {
  huntId: string;
  listing: Listing;
  serverFees: FeeEntry[];
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
  const [saving, setSaving] = useState(false);

  const patchPins = usePatchPins(huntId);
  const createOverride = useCreateOverride(huntId, listing.id);
  const upsertFee = useUpsertFee(huntId, listing.id);

  const isDirty = useMemo(
    () => isDraftDirty(baselinePins, draftPins, draftOverrides, draftFees, serverFees),
    [baselinePins, draftPins, draftOverrides, draftFees, serverFees],
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

  const resetDraft = useCallback(() => {
    setDraftPins({ ...baselinePins });
    setDraftOverrides(new Map());
    setDraftFees(new Map());
  }, [baselinePins]);

  const saveAll = useCallback(async (): Promise<boolean> => {
    if (!isDirty) return true;

    setSaving(true);
    const pinsChanged = isPinsDirty(baselinePins, draftPins);
    const overrideEntries = [...draftOverrides.entries()];
    const feeSlots = changedFeeSlots(draftFees, serverFees);

    type Task =
      | { kind: "pins" }
      | { kind: "override"; key: string; entry: DraftOverride }
      | { kind: "fee"; slot: string; amount: number | null; state: "manual" | "extracted" | "unknown" };

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
      });
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
        return upsertFee.mutateAsync({
          slot: task.slot,
          amount: task.amount,
          value_state: task.state,
        });
      }),
    );

    const failed: string[] = [];
    const succeededOverrides = new Set<string>();
    const succeededFees = new Set<string>();

    results.forEach((result, i) => {
      const task = tasks[i];
      if (result.status === "fulfilled") {
        if (task.kind === "override") succeededOverrides.add(task.key);
        if (task.kind === "fee") succeededFees.add(task.slot);
        return;
      }
      if (task.kind === "pins") failed.push("floor plan pin");
      else if (task.kind === "override") failed.push(`override (${task.key})`);
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

    setSaving(false);

    if (failed.length === 0) {
      const hadOverrides = overrideEntries.length > 0;
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
    patchPins,
    createOverride,
    upsertFee,
    listing.id,
  ]);

  const value = useMemo(
    () => ({
      draftPins,
      draftOverrides,
      draftFees,
      isDirty,
      saving,
      setDraftPin,
      setDraftOverride,
      clearDraftOverride,
      setDraftFee,
      clearDraftFee,
      resetDraft,
      saveAll,
    }),
    [
      draftPins,
      draftOverrides,
      draftFees,
      isDirty,
      saving,
      setDraftPin,
      setDraftOverride,
      clearDraftOverride,
      setDraftFee,
      clearDraftFee,
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
