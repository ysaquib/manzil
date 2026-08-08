// Visits data hooks (VC-2). Reads via supabase-js — they are continuously
// rendered and Realtime-backed (VC-5) — and every mutation via apiClient, per
// the two-client split in frontend/AGENTS.md. Endpoint and table assumptions:
// frontend/API_ASSUMPTIONS.md.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";
import type { SaveEntriesVariables } from "../../lib/offline";
import { SAVE_ENTRIES_KEY } from "../../lib/offline";
import { supabase } from "../../lib/supabase";
import type {
  Visit,
  VisitCustomItem,
  VisitDefect,
  VisitEntry,
  VisitEntryConflict,
  VisitFeeProposal,
  VisitTemplateItem,
  VisitUnitGroupScore,
} from "./types";

type VisitCreate = components["schemas"]["VisitCreate"];
type VisitResponse = components["schemas"]["VisitResponse"];
type VisitPatch = components["schemas"]["VisitPatch"];
type VisitUnitInput = components["schemas"]["VisitUnitInput"];
type VisitUnitResponse = components["schemas"]["VisitUnitResponse"];
type VisitUnitPatch = components["schemas"]["VisitUnitPatch"];
type VisitCustomItemCreate = components["schemas"]["VisitCustomItemCreate"];
type VisitEntryInput = components["schemas"]["VisitEntryInput"];
type VisitDefectCreate = components["schemas"]["VisitDefectCreate"];
type VisitDefectPatch = components["schemas"]["VisitDefectPatch"];
type VisitFeeProposalCreate = components["schemas"]["VisitFeeProposalCreate"];

// `properties` is globally readable to any authenticated user (§8.3), so the
// Visit carries its own Property identity rather than the list cross-referencing
// the listings cache — one query, and it still works for a Property whose
// Listing was archived.
const VISIT_SELECT = "*, visit_units(*), property:properties(id, name, canonical_address)";

/** Every Visit in the hunt, newest first. */
export function useVisits(huntId: string) {
  return useQuery({
    queryKey: ["visits", huntId],
    queryFn: async (): Promise<Visit[]> => {
      const { data, error } = await supabase
        .from("visits")
        .select(VISIT_SELECT)
        .eq("hunt_id", huntId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as Visit[];
    },
  });
}

/** Visits for one Property — the drawer's list (VC-8). */
export function usePropertyVisits(huntId: string, propertyId: string | undefined) {
  return useQuery({
    queryKey: ["visits", huntId, "property", propertyId],
    enabled: Boolean(propertyId),
    queryFn: async (): Promise<Visit[]> => {
      const { data, error } = await supabase
        .from("visits")
        .select(VISIT_SELECT)
        .eq("hunt_id", huntId)
        .eq("property_id", propertyId!)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as Visit[];
    },
  });
}

/** One Visit by id. RLS scopes it, so no hunt filter is needed. */
export function useVisit(visitId: string | undefined) {
  return useQuery({
    queryKey: ["visit", visitId],
    enabled: Boolean(visitId),
    queryFn: async (): Promise<Visit | null> => {
      const { data, error } = await supabase
        .from("visits")
        .select(VISIT_SELECT)
        .eq("id", visitId!)
        .maybeSingle();
      if (error) throw error;
      return (data ?? null) as unknown as Visit | null;
    },
  });
}

/**
 * The built-in checklist template for one version.
 *
 * `visits.template_version` is frozen per Visit, so a Visit always resolves
 * against the template it was created with — editing the template never
 * rewrites a finished Visit. Global read-only reference data, so it is cached
 * indefinitely: it can only change by migration.
 */
export function useVisitTemplate(version: number | undefined) {
  return useQuery({
    queryKey: ["visit_template_items", version],
    enabled: version !== undefined,
    staleTime: Infinity,
    gcTime: Infinity,
    queryFn: async (): Promise<VisitTemplateItem[]> => {
      const { data, error } = await supabase
        .from("visit_template_items")
        .select("*")
        .eq("version", version!)
        .order("display_order");
      if (error) throw error;
      return (data ?? []) as unknown as VisitTemplateItem[];
    },
  });
}

export function useVisitCustomItems(visitId: string | undefined) {
  return useQuery({
    queryKey: ["visit_custom_items", visitId],
    enabled: Boolean(visitId),
    queryFn: async (): Promise<VisitCustomItem[]> => {
      const { data, error } = await supabase
        .from("visit_custom_items")
        .select("*")
        .eq("visit_id", visitId!)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as VisitCustomItem[];
    },
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

function invalidateVisits(qc: ReturnType<typeof useQueryClient>, huntId: string) {
  void qc.invalidateQueries({ queryKey: ["visits", huntId] });
}

export function useCreateVisit(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: VisitCreate) =>
      apiFetch<VisitResponse>(`/v1/hunts/${huntId}/visits`, { method: "POST", body }),
    onSuccess: () => invalidateVisits(qc, huntId),
  });
}

export function usePatchVisit(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, body }: { visitId: string; body: VisitPatch }) =>
      apiFetch<VisitResponse>(`/v1/visits/${visitId}`, {
        method: "PATCH",
        body,
        // `onSuccess` reads `visit.id`, and a demo write resolves without a
        // response — so without this the control throws instead of quietly
        // doing nothing (R2 M5). Only the id is read, so only the id is needed.
        demoResult: () => ({ id: visitId }) as VisitResponse,
      }),
    onSuccess: (visit) => {
      invalidateVisits(qc, huntId);
      void qc.invalidateQueries({ queryKey: ["visit", visit.id] });
    },
  });
}

export function useDeleteVisit(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (visitId: string) =>
      apiFetch<void>(`/v1/visits/${visitId}`, { method: "DELETE" }),
    onSuccess: () => invalidateVisits(qc, huntId),
  });
}

export function useAddVisitUnit(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, body }: { visitId: string; body: VisitUnitInput }) =>
      apiFetch<VisitUnitResponse>(`/v1/visits/${visitId}/units`, { method: "POST", body }),
    onSuccess: (_unit, { visitId }) => {
      invalidateVisits(qc, huntId);
      void qc.invalidateQueries({ queryKey: ["visit", visitId] });
    },
  });
}

export function usePatchVisitUnit(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      visitId,
      unitId,
      body,
    }: {
      visitId: string;
      unitId: string;
      body: VisitUnitPatch;
    }) =>
      apiFetch<VisitUnitResponse>(`/v1/visits/${visitId}/units/${unitId}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: (_unit, { visitId }) => {
      invalidateVisits(qc, huntId);
      void qc.invalidateQueries({ queryKey: ["visit", visitId] });
    },
  });
}

export function useDeleteVisitUnit(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, unitId }: { visitId: string; unitId: string }) =>
      apiFetch<void>(`/v1/visits/${visitId}/units/${unitId}`, { method: "DELETE" }),
    onSuccess: (_void, { visitId }) => {
      invalidateVisits(qc, huntId);
      void qc.invalidateQueries({ queryKey: ["visit", visitId] });
    },
  });
}

/** Current answers for one Visit, read through the newest-per-identity view. */
export function useVisitEntries(visitId: string | undefined) {
  return useQuery({
    queryKey: ["visit_entries", visitId],
    enabled: Boolean(visitId),
    queryFn: async (): Promise<VisitEntry[]> => {
      const { data, error } = await supabase
        .from("current_visit_entries")
        .select("*")
        .eq("visit_id", visitId!);
      if (error) throw error;
      return (data ?? []) as unknown as VisitEntry[];
    },
  });
}

/**
 * Append a batch of answers.
 *
 * The one write path for answers, and the queue that survives a dead signal
 * (VC-6). Append-only: clearing an answer means sending `value: null`.
 *
 * Three things here are dictated by having to work offline. The mutation
 * function and its cache invalidation live in `lib/offline.ts` against
 * `SAVE_ENTRIES_KEY`, because a write restored from storage is rebuilt in a
 * fresh page where this closure no longer exists. `visitId` therefore travels
 * as a variable rather than being captured. And the optimistic update is not a
 * nicety: offline the server round trip never comes, so without it a tapped
 * answer would sit blank until reconnection — on a tour that reads as a lost
 * answer, and it gets tapped again.
 */
export function useSaveVisitEntries(
  visitId: string,
  authorUserId: string | null,
  /**
   * Which member an answer belongs to — the author for an Impression, nobody
   * otherwise. The server decides this for real; the optimistic row has to
   * agree with it or a rating would briefly land under the wrong identity.
   * Passed in because owner depends on the *item's* kind, which lives with the
   * caller, and it is deliberately not sent over the wire.
   */
  ownerOf: (entry: VisitEntryInput) => string | null = () => null,
) {
  const qc = useQueryClient();
  const mutation = useMutation<unknown, Error, SaveEntriesVariables, { previous?: VisitEntry[] }>({
    mutationKey: SAVE_ENTRIES_KEY,
    onMutate: async ({ entries }) => {
      await qc.cancelQueries({ queryKey: ["visit_entries", visitId] });
      const previous = qc.getQueryData<VisitEntry[]>(["visit_entries", visitId]);
      qc.setQueryData<VisitEntry[]>(["visit_entries", visitId], (current) =>
        applyOptimisticEntries(
          current ?? [],
          entries as VisitEntryInput[],
          visitId,
          authorUserId,
          ownerOf,
        ),
      );
      return { previous };
    },
    onError: (_error, _variables, context) => {
      // Put the server's version back. The queued write itself is not lost —
      // it stays paused and flushes on reconnect — but a *failed* write must
      // not leave an answer on screen that nothing is going to save.
      if (context?.previous) qc.setQueryData(["visit_entries", visitId], context.previous);
    },
  });

  return {
    ...mutation,
    /** Callers pass entries; the Visit is attached here so it is carried, not captured. */
    mutate: (entries: VisitEntryInput[]) => mutation.mutate({ visitId, entries }),
  };
}

/**
 * Fold a pending write into the cached current answers.
 *
 * Mirrors `current_visit_entries`: newest row per `(item, unit, owner)` wins,
 * so an optimistic row replaces the identity it targets rather than being
 * appended alongside it.
 */
export function applyOptimisticEntries(
  current: VisitEntry[],
  entries: VisitEntryInput[],
  visitId: string,
  authorUserId: string | null,
  ownerOf: (entry: VisitEntryInput) => string | null = () => null,
): VisitEntry[] {
  const next = [...current];
  for (const entry of entries) {
    const owner = ownerOf(entry);
    const at = next.findIndex(
      (candidate) =>
        candidate.item_key === entry.item_key &&
        (candidate.visit_unit_id ?? null) === (entry.visit_unit_id ?? null) &&
        (candidate.owner_user_id ?? null) === owner,
    );
    const existing = at >= 0 ? next[at] : undefined;
    const optimistic: VisitEntry = {
      // Marked so nothing mistakes it for a saved row — most importantly the
      // next write's `prev_entry_id`, which must never claim a row the server
      // has never seen.
      id: `optimistic:${entry.item_key}:${entry.visit_unit_id ?? ""}:${owner ?? ""}`,
      visit_id: visitId,
      item_key: entry.item_key,
      is_custom: entry.is_custom ?? false,
      visit_unit_id: entry.visit_unit_id ?? null,
      owner_user_id: owner,
      author_user_id: authorUserId ?? existing?.author_user_id ?? "",
      value: "value" in entry ? entry.value : (existing?.value ?? null),
      answer_text: "answer_text" in entry ? (entry.answer_text ?? null) : (existing?.answer_text ?? null),
      note: "note" in entry ? (entry.note ?? null) : (existing?.note ?? null),
      prev_entry_id: entry.prev_entry_id ?? null,
      created_at: new Date().toISOString(),
    };
    if (at >= 0) next[at] = optimistic;
    else next.push(optimistic);
  }
  return next;
}

/** True for a row that exists only in the cache and has no server identity yet. */
export function isOptimisticEntry(entry: Pick<VisitEntry, "id">): boolean {
  return entry.id.startsWith("optimistic:");
}

/**
 * Unresolved answer forks on this Visit.
 *
 * Read straight from `visit_entry_conflicts`, which decides what counts as an
 * open fork; the client only groups the branches for display.
 */
export function useVisitEntryConflicts(visitId: string | undefined) {
  return useQuery({
    queryKey: ["visit_entry_conflicts", visitId],
    enabled: Boolean(visitId),
    queryFn: async (): Promise<VisitEntryConflict[]> => {
      const { data, error } = await supabase
        .from("visit_entry_conflicts")
        .select("*")
        .eq("visit_id", visitId!)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as VisitEntryConflict[];
    },
  });
}

/** Live defects for one Visit; soft-deleted rows never surface. */
export function useVisitDefects(visitId: string | undefined) {
  return useQuery({
    queryKey: ["visit_defects", visitId],
    enabled: Boolean(visitId),
    queryFn: async (): Promise<VisitDefect[]> => {
      const { data, error } = await supabase
        .from("visit_defects")
        .select("*")
        .eq("visit_id", visitId!)
        .is("deleted_at", null)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as VisitDefect[];
    },
  });
}

function invalidateDefects(qc: ReturnType<typeof useQueryClient>, visitId: string) {
  void qc.invalidateQueries({ queryKey: ["visit_defects", visitId] });
}

export function useCreateVisitDefect(visitId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: VisitDefectCreate) =>
      apiFetch<VisitDefect>(`/v1/visits/${visitId}/defects`, { method: "POST", body }),
    onSuccess: () => invalidateDefects(qc, visitId),
  });
}

export function usePatchVisitDefect(visitId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ defectId, body }: { defectId: string; body: VisitDefectPatch }) =>
      apiFetch<VisitDefect>(`/v1/visits/${visitId}/defects/${defectId}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => invalidateDefects(qc, visitId),
  });
}

export function useDeleteVisitDefect(visitId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (defectId: string) =>
      apiFetch<void>(`/v1/visits/${visitId}/defects/${defectId}`, { method: "DELETE" }),
    onSuccess: () => invalidateDefects(qc, visitId),
  });
}

export function useCreateVisitCustomItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, body }: { visitId: string; body: VisitCustomItemCreate }) =>
      apiFetch<VisitCustomItem>(`/v1/visits/${visitId}/custom-items`, {
        method: "POST",
        body,
      }),
    onSuccess: (_item, { visitId }) =>
      void qc.invalidateQueries({ queryKey: ["visit_custom_items", visitId] }),
  });
}

// ---------------------------------------------------------------------------
// Fee Proposals (VC-7)
// ---------------------------------------------------------------------------

/**
 * Standing offers made from this Visit.
 *
 * A tour produces the best cost data in the system, and it still never writes
 * to a Listing on its own (DESIGN §9.7) — this is the offer, and the drawer is
 * where it gets decided.
 */
export function useVisitFeeProposals(visitId: string | undefined) {
  return useQuery({
    queryKey: ["visit_fee_proposals", visitId],
    enabled: Boolean(visitId),
    queryFn: async (): Promise<VisitFeeProposal[]> => {
      const { data, error } = await supabase
        .from("visit_fee_proposals")
        .select("*")
        .eq("visit_id", visitId!)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as VisitFeeProposal[];
    },
  });
}

/** Pending offers addressed to one Listing — what the drawer renders. */
export function useListingFeeProposals(huntListingId: string | undefined) {
  return useQuery({
    queryKey: ["visit_fee_proposals", "listing", huntListingId],
    enabled: Boolean(huntListingId),
    queryFn: async (): Promise<VisitFeeProposal[]> => {
      const { data, error } = await supabase
        .from("visit_fee_proposals")
        .select("*")
        .eq("hunt_listing_id", huntListingId!)
        .eq("status", "pending")
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as VisitFeeProposal[];
    },
  });
}

function invalidateProposals(qc: ReturnType<typeof useQueryClient>, visitId?: string) {
  void qc.invalidateQueries({ queryKey: ["visit_fee_proposals"] });
  if (visitId) void qc.invalidateQueries({ queryKey: ["visit_fee_proposals", visitId] });
}

export function useCreateFeeProposal(visitId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: VisitFeeProposalCreate) =>
      apiFetch<VisitFeeProposal>(`/v1/visits/${visitId}/fee-proposals`, {
        method: "POST",
        body,
      }),
    onSuccess: () => invalidateProposals(qc, visitId),
  });
}

/**
 * Accept or reject an offer.
 *
 * The Visit travels in the variables rather than the hook argument: the drawer
 * shows every pending offer for a Listing, and those can come from more than
 * one tour.
 */
export function useDecideFeeProposal(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      visitId,
      proposalId,
      action,
    }: {
      visitId: string;
      proposalId: string;
      action: "accept" | "reject";
    }) =>
      apiFetch<VisitFeeProposal>(`/v1/visits/${visitId}/fee-proposals/${proposalId}/decision`, {
        method: "POST",
        body: { action },
        // `onSuccess` reads three fields off the response. In demo mode the
        // decision is never sent, so report it as rejected: that is the branch
        // which invalidates nothing, and claiming an acceptance would tell the
        // cache a fee was written when none was (R2 M5).
        demoResult: () =>
          ({ id: proposalId, visit_id: visitId, status: "rejected" }) as VisitFeeProposal,
      }),
    onSuccess: (proposal) => {
      invalidateProposals(qc, proposal.visit_id);
      if (proposal.status !== "accepted") return;
      // Accepting performed a real cost write on another table, so this
      // invalidates exactly what `useUpsertFee` and `useCreateOverride`
      // invalidate — a mutation must invalidate what it *causes*, and here the
      // cause is the entire point.
      void qc.invalidateQueries({ queryKey: ["fee_checklist", proposal.hunt_listing_id] });
      void qc.invalidateQueries({ queryKey: ["overrides", proposal.hunt_listing_id] });
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
    },
  });
}

export function useWithdrawFeeProposal(visitId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (proposalId: string) =>
      apiFetch<void>(`/v1/visits/${visitId}/fee-proposals/${proposalId}`, { method: "DELETE" }),
    onSuccess: () => invalidateProposals(qc, visitId),
  });
}

/**
 * The Unit Group roll-up (VC-8).
 *
 * One score per `(hunt_listing_id, unit_group_key)`, computed by the
 * `visit_unit_group_scores` view: latest tour per door, then the best door in
 * the group. The client never re-derives that — the rules live in one place.
 */
export function useVisitUnitGroupScores(huntId: string) {
  return useQuery({
    queryKey: ["visit_unit_group_scores", huntId],
    queryFn: async (): Promise<VisitUnitGroupScore[]> => {
      // The view carries no hunt_id; RLS already scopes it to the caller's
      // Hunts, and the Overview reads every row it is allowed to see.
      const { data, error } = await supabase.from("visit_unit_group_scores").select("*");
      if (error) throw error;
      return (data ?? []) as unknown as VisitUnitGroupScore[];
    },
  });
}

/** Index the roll-up the way the Overview looks it up: listing + group. */
export function visitScoreKey(huntListingId: string, unitGroupKey: string | null): string {
  return `${huntListingId}:${unitGroupKey ?? ""}`;
}
