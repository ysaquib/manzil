// Hunts data hooks (Phase 1 plan §5.2). Reads via supabase-js; mutations via
// apiClient with generated DTOs. Assumptions: frontend/API_ASSUMPTIONS.md.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../auth/useAuth";
import { apiFetch } from "../../lib/apiClient";
import { demoPrincipalId } from "../../lib/demo";
import type { components } from "../../lib/generated/api";
import { supabase } from "../../lib/supabase";
import { useGhostMutationPath } from "../admin/useGhostMode";

type HuntCreate = components["schemas"]["HuntCreate"];
type HuntUpdate = components["schemas"]["HuntUpdate"];
type HuntSettingsPatch = components["schemas"]["HuntSettingsPatch"];

export interface Hunt {
  id: string;
  name: string;
  owner_id: string;
  domain: string;
  rubric_version: number;
  settings: Record<string, unknown>;
  archived_at: string | null;
  locked_at: string | null;
  locked_by: string | null;
  created_at: string;
}

export function useHunts() {
  const { session } = useAuth();
  const userId = session?.user.id;

  return useQuery({
    queryKey: ["hunts", "mine", userId],
    queryFn: async (): Promise<Hunt[]> => {
      if (!userId) return [];

      // Site Admin SELECT policies deliberately expose every Hunt for Ghost
      // View. The switcher means "Your hunts", so membership must be an
      // explicit query condition rather than an accidental consequence of RLS.
      const { data, error } = await supabase
        .from("hunts")
        .select("*, hunt_members!inner(user_id)")
        .eq("hunt_members.user_id", userId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as Hunt[];
    },
    enabled: Boolean(userId),
  });
}

export interface HuntDeletionImpact {
  hunt_id: string;
  name: string;
  members: number;
  listings: number;
  jobs: number;
  visits: number;
}

export function useHuntDeletionImpact(huntId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["hunts", huntId, "deletion-impact"],
    queryFn: () => apiFetch<HuntDeletionImpact>(`/v1/hunts/${huntId}/deletion-impact`),
    enabled,
  });
}

export function useDeleteHuntPermanently(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (confirmationName: string) =>
      apiFetch<HuntDeletionImpact>(`/v1/hunts/${huntId}`, {
        method: "DELETE",
        body: { confirmation_name: confirmationName },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunts"] });
      void qc.removeQueries({ queryKey: ["hunts", huntId] });
    },
  });
}

export function useHunt(huntId: string) {
  return useQuery({
    queryKey: ["hunts", huntId],
    queryFn: async (): Promise<Hunt> => {
      const { data, error } = await supabase.from("hunts").select("*").eq("id", huntId).single();
      if (error) throw error;
      return data as Hunt;
    },
    enabled: Boolean(huntId),
  });
}

export function useCreateHunt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: HuntCreate) => apiFetch<Hunt>("/v1/hunts", { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunts"] }),
  });
}

export function usePatchHunt(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (body: HuntUpdate) =>
      apiFetch<Hunt>(mutationPath(`/v1/hunts/${huntId}`), { method: "PATCH", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunts"] }),
  });
}

// Hunt-wide Overview filters (§13.2, §20 2026-07-19) — hand-typed like the
// read models; the PUT body is opaque to the API, so no generated DTO exists.
export interface SharedFiltersRow {
  hunt_id: string;
  filters: Record<string, unknown>;
  updated_by: string;
  updated_at: string;
}

export function useSharedFilters(huntId: string) {
  return useQuery({
    queryKey: ["hunt_shared_filters", huntId],
    queryFn: async (): Promise<SharedFiltersRow | null> => {
      const { data, error } = await supabase
        .from("hunt_shared_filters")
        .select("*")
        .eq("hunt_id", huntId)
        .maybeSingle();
      if (error) throw error;
      return data as SharedFiltersRow | null;
    },
  });
}

export function usePublishSharedFilters(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (filters: object) =>
      apiFetch<SharedFiltersRow>(mutationPath(`/v1/hunts/${huntId}/shared-filters`), {
        method: "PUT",
        body: { filters },
        demoResult: () => ({
          hunt_id: huntId,
          filters: filters as Record<string, unknown>,
          updated_by: demoPrincipalId() ?? "",
          updated_at: new Date().toISOString(),
        }),
      }),
    onSuccess: (saved) => {
      qc.setQueryData(["hunt_shared_filters", huntId], saved);
    },
  });
}

export function usePatchHuntSettings(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (body: HuntSettingsPatch) =>
      apiFetch<Hunt>(mutationPath(`/v1/hunts/${huntId}/settings`), { method: "PATCH", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunts"] });
      // Scoring-affecting settings take the bump+rescore path (§8.2) — the
      // scores re-fetch picks the new totals up when the rescore job lands.
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
      void qc.invalidateQueries({ queryKey: ["jobs", huntId] });
    },
  });
}
