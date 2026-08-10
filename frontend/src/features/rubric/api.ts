// Rubric data hooks (P1-12). Catalog + rubric read directly from Supabase;
// the save goes through PUT /v1/hunts/{id}/rubric with the DESIGN §8.2 pinned
// option shape — NOT the generated RubricOption, which conflicts with the
// pinned contract (frontend/API_ASSUMPTIONS.md conflict #1).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useMemo } from "react";

import { apiFetch } from "../../lib/apiClient";
import type { NonNegotiable, RubricOption } from "../../lib/contracts";
import { supabase } from "../../lib/supabase";
import { useGhostMutationPath } from "../admin/useGhostMode";
import { catalogWithCustomLabels } from "./customCriterion";
import type { ValueSchema } from "./widgets/types";

export interface CatalogEntry {
  key: string;
  label: string;
  category: string;
  domain: "rent" | "buy" | "both";
  fact_scope: "property" | "floor_plan" | "mixed" | "composed";
  value_schema: ValueSchema;
  default_options: RubricOption[];
  extraction_hint: string;
  requires_tool: string | null;
  refresh_class: string;
  /** Only ever set on the synthetic entry for a custom Criterion (§9.2). */
  acquisition?: CustomAcquisition;
}

export interface RubricCriterion {
  id?: string;
  hunt_id?: string;
  catalog_key: string | null;
  custom_def: CustomCriterionDef | null;
  enabled: boolean;
  options: RubricOption[];
  unknown_delta: number;
  non_negotiable: NonNegotiable | null;
  is_bonus: boolean;
  position: number;
}

export type CustomRoute = null | "maps" | "vision" | "web_search";

export interface CustomRouteModifiers {
  avoid_highways?: boolean;
  avoid_tolls?: boolean;
  avoid_ferries?: boolean;
}

/**
 * How a custom Criterion's value is acquired. `extracted` is the pipeline —
 * listing text or Maps. `manual` has no producer at all: a person answers it on
 * each Listing and the answer is stored as an ordinary Override (DESIGN §9.2).
 * Absent in older stored definitions, which are `extracted`.
 */
export type CustomAcquisition = "extracted" | "manual";

export interface CustomCriterionDef {
  schema_version: 1;
  key: string;
  label: string;
  description: string;
  fact_scope: "property" | "floor_plan";
  value_schema: ValueSchema;
  acquisition?: CustomAcquisition;
  requires_tool: CustomRoute;
  refresh_class: "listing_details" | "location" | "manual";
  routing_confirmed: boolean;
  route_modifiers?: CustomRouteModifiers | null;
}

/** Manual Criteria are answered by hand; nothing extracts or refetches them. */
export function isManualCriterion(custom: CustomCriterionDef | null | undefined): boolean {
  return custom?.acquisition === "manual";
}

export interface CustomRoutingResponse {
  key: string;
  suggested_requires_tool: CustomRoute;
  reason: string;
  supported: boolean;
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

/** Catalog merged with this hunt's custom Criterion labels (drawer, compare, breakdown). */
export function useResolvedCatalog(huntId: string, domain: "rent" | "buy" = "rent") {
  const { data: catalog = [], ...catalogQuery } = useCatalog(domain);
  const { data: rubric = [], ...rubricQuery } = useRubric(huntId);
  const resolved = useMemo(
    () => catalogWithCustomLabels(catalog, rubric),
    [catalog, rubric],
  );
  return {
    data: resolved,
    isLoading: catalogQuery.isLoading || rubricQuery.isLoading,
    error: catalogQuery.error ?? rubricQuery.error,
  };
}

export function usePutRubric(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (criteria: RubricCriterion[]) =>
      apiFetch<RubricCriterion[]>(mutationPath(`/v1/hunts/${huntId}/rubric`), {
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

export function useClassifyCustomRouting(huntId: string) {
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (body: { label: string; description: string }) =>
      apiFetch<CustomRoutingResponse>(mutationPath(`/v1/hunts/${huntId}/rubric/custom-routing`), {
        method: "POST",
        body,
        // Classification is an LLM call, so the demo genuinely cannot run it —
        // and its caller reads four fields off the response (R2 M5). Answer
        // `supported: false`, which is the branch the modal already renders as
        // "we can't route this", rather than inventing a routing decision that
        // no model made.
        demoResult: () => ({
          key: body.label
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_|_$/g, ""),
          suggested_requires_tool: null as CustomRoute,
          reason: "Custom Criteria are not classified in the demo.",
          supported: false,
        }),
      }),
  });
}
