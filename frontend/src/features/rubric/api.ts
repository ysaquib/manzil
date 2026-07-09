// Rubric data hooks (P1-12). Catalog + rubric read directly from Supabase;
// the save goes through PUT /v1/hunts/{id}/rubric with the DESIGN §8.2 pinned
// option shape — NOT the generated RubricOption, which conflicts with the
// pinned contract (frontend/API_ASSUMPTIONS.md conflict #1).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { NonNegotiable, RubricOption } from "../../lib/contracts";
import { supabase } from "../../lib/supabase";
import type { ValueSchema } from "./widgets/types";

export interface CatalogEntry {
  key: string;
  label: string;
  category: string;
  domain: "rent" | "buy" | "both";
  value_schema: ValueSchema;
  default_options: RubricOption[];
  extraction_hint: string;
  requires_tool: string | null;
  refresh_class: string;
}

export interface RubricCriterion {
  id?: string;
  hunt_id?: string;
  catalog_key: string | null;
  custom_def: Record<string, unknown> | null;
  enabled: boolean;
  options: RubricOption[];
  unknown_delta: number;
  non_negotiable: NonNegotiable | null;
  is_bonus: boolean;
  position: number;
}

export function useCatalog(domain: "rent" | "buy" = "rent") {
  return useQuery({
    queryKey: ["criteria_catalog", domain],
    // The catalog is a seeded global table — effectively static per deploy.
    staleTime: Infinity,
    queryFn: async (): Promise<CatalogEntry[]> => {
      const { data, error } = await supabase
        .from("criteria_catalog")
        .select("*")
        .in("domain", [domain, "both"]);
      if (error) throw error;
      return (data ?? []) as CatalogEntry[];
    },
  });
}

export function useRubric(huntId: string) {
  return useQuery({
    queryKey: ["rubric_criteria", huntId],
    queryFn: async (): Promise<RubricCriterion[]> => {
      const { data, error } = await supabase
        .from("rubric_criteria")
        .select("*")
        .eq("hunt_id", huntId)
        .order("position");
      if (error) throw error;
      return (data ?? []) as RubricCriterion[];
    },
  });
}

export function usePutRubric(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (criteria: RubricCriterion[]) =>
      apiFetch<RubricCriterion[]>(`/v1/hunts/${huntId}/rubric`, {
        method: "PUT",
        body: { criteria },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["rubric_criteria", huntId] });
      // Rubric mutation bumps rubric_version + enqueues the hunt rescore (§9.2).
      void qc.invalidateQueries({ queryKey: ["hunts"] });
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
      void qc.invalidateQueries({ queryKey: ["jobs", huntId] });
    },
  });
}
