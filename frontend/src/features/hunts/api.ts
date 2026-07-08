// Hunts data hooks (Phase 1 plan §5.2). Reads via supabase-js; the create
// mutation via apiClient. Full wiring lands with P1-9; these are the seams.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import { supabase } from "../../lib/supabase";

export interface Hunt {
  id: string;
  name: string;
  owner_id: string;
  domain: string;
  rubric_version: number;
  settings: Record<string, unknown>;
  archived_at: string | null;
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

export function useCreateHunt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; domain?: "rent" | "buy" }) =>
      apiFetch<Hunt>("/v1/hunts", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["hunts"] }),
  });
}
