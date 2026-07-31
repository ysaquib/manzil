// Local-first answer writes (VC-6, plan §7.2).
//
// A tour happens in a basement, a stairwell, a concrete-walled unit with no
// signal. Losing twenty minutes of notes would end use of the feature, so
// answers are written optimistically, queued when the network is gone, and
// flushed on reconnect — surviving a reload in between.
//
// This uses TanStack Query's own paused-mutation persistence rather than a
// bespoke IndexedDB queue: entry writes are already a single batch mutation,
// which is exactly the shape that mechanism handles well.
//
// The consequence that shapes this file: a resumed mutation is rebuilt from
// storage in a fresh page, where the React closure that created it no longer
// exists. Anything the write needs — the function, its Visit, the cache updates
// — has to be registered on the client itself and carried in the variables,
// never captured. That is why the mutation function lives here and not in a
// hook, and why `visitId` travels as a variable.
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import type { QueryClient } from "@tanstack/react-query";
import type { PersistQueryClientOptions } from "@tanstack/react-query-persist-client";

import { apiFetch } from "./apiClient";

/** Shared by the hook and the persisted default, so they cannot drift apart. */
export const SAVE_ENTRIES_KEY = ["visit_entries", "save"] as const;

export interface SaveEntriesVariables {
  /** Carried, not captured: the closure is gone by the time this is resumed. */
  visitId: string;
  entries: unknown[];
}

/**
 * Which cached data is allowed to outlive the tab.
 *
 * Deliberately narrow. Persisting the whole cache would resurrect stale
 * listings, jobs and fees on a cold start — data the rest of the app expects to
 * refetch. Only what a checklist needs to render offline is kept: the answers
 * themselves, the Visit, its defects, and the template (which changes only by
 * migration).
 */
const PERSISTED_QUERY_PREFIXES = new Set([
  "visit",
  "visits",
  "visit_entries",
  "visit_defects",
  "visit_units",
  "visit_template",
  "visit_custom_items",
  "visit_entry_conflicts",
]);

const STORAGE_KEY = "manzil-offline-cache";

/**
 * Teach the client how to replay a queued answer write.
 *
 * Called once at startup, before the app renders, so a mutation restored from
 * storage always finds its function already registered — a restored mutation
 * with no registered default is inert, and its answer would never land.
 */
export function installMutationDefaults(queryClient: QueryClient) {
  queryClient.setMutationDefaults(SAVE_ENTRIES_KEY, {
    mutationFn: async ({ visitId, entries }: SaveEntriesVariables) =>
      apiFetch(`/v1/visits/${visitId}/entries`, {
        method: "PUT",
        body: { entries },
      }),
    onSettled: (_data, _error, variables) => {
      const { visitId } = variables as SaveEntriesVariables;
      void queryClient.invalidateQueries({ queryKey: ["visit_entries", visitId] });
      // Saving an answer can create a row in another table: marking a Check as a
      // problem promotes it into the defect log (VC-4), and a queued write that
      // flushes late can fork an answer (VC-6). The write that causes those has
      // to invalidate them, or they silently lag behind the checklist.
      void queryClient.invalidateQueries({ queryKey: ["visit_defects", visitId] });
      void queryClient.invalidateQueries({ queryKey: ["visit_entry_conflicts", visitId] });
    },
    // `onSettled` rather than `onSuccess`: a write that failed still needs the
    // cache reconciled, otherwise an optimistic answer that never landed stays
    // on screen looking saved.
    retry: 3,
  });
}

/**
 * Where the cache is kept between sessions, or `null` where it cannot be.
 *
 * `localStorage` is absent under SSR and throws outright in some privacy modes.
 * Offline support is an enhancement — losing it must never stop the app from
 * loading, so this degrades to null and the caller mounts a plain provider.
 */
export function createOfflinePersister() {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return createSyncStoragePersister({ storage: window.localStorage, key: STORAGE_KEY });
  } catch {
    return null;
  }
}

/** Options for `PersistQueryClientProvider`, which owns restore and resume. */
export function persistOptions(
  persister: NonNullable<ReturnType<typeof createOfflinePersister>>,
): Omit<PersistQueryClientOptions, "queryClient"> {
  return {
    persister,
    // A tour is a day, not a week. Beyond this the cached answers are more
    // likely to mislead than to help, and the server copy is authoritative.
    maxAge: 1000 * 60 * 60 * 24,
    dehydrateOptions: {
      // Only *paused* mutations are worth keeping. A mutation still in flight
      // when the tab died has an unknowable outcome, and replaying it blindly
      // would append a duplicate answer.
      shouldDehydrateMutation: (mutation) => mutation.state.isPaused,
      shouldDehydrateQuery: (query) => {
        const head = query.queryKey[0];
        return typeof head === "string" && PERSISTED_QUERY_PREFIXES.has(head);
      },
    },
  };
}
