// Hunts data hooks (Phase 1 plan §5.2). Reads via supabase-js; mutations via
// apiClient with generated DTOs. Assumptions: frontend/API_ASSUMPTIONS.md.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";
import { supabase } from "../../lib/supabase";

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
  created_at: string;
}

export function useHunts() {
  return useQuery({
    queryKey: ["hunts"],
    queryFn: async (): Promise<Hunt[]> => {
      const { data, error } = await supabase
        .from("hunts")
        .select("*")
        .is("archived_at", null)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as Hunt[];
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
  return useMutation({
    mutationFn: (body: HuntUpdate) =>
      apiFetch<Hunt>(`/v1/hunts/${huntId}`, { method: "PATCH", body }),
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
  return useMutation({
    mutationFn: (filters: object) =>
      apiFetch<SharedFiltersRow>(`/v1/hunts/${huntId}/shared-filters`, {
        method: "PUT",
        body: { filters },
      }),
    onSuccess: (saved) => {
      qc.setQueryData(["hunt_shared_filters", huntId], saved);
    },
  });
}

export function usePatchHuntSettings(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: HuntSettingsPatch) =>
      apiFetch<Hunt>(`/v1/hunts/${huntId}/settings`, { method: "PATCH", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunts"] });
      // Scoring-affecting settings take the bump+rescore path (§8.2) — the
      // scores re-fetch picks the new totals up when the rescore job lands.
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
      void qc.invalidateQueries({ queryKey: ["jobs", huntId] });
    },
  });
}
