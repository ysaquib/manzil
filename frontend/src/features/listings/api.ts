// Listings data hooks (P1-10/P1-11). Reads via supabase-js (the continuously
// rendered table data); every mutation via apiClient — rescore-on-mutation
// means score changes arrive by re-fetch, never synchronously. Endpoint and
// table assumptions: frontend/API_ASSUMPTIONS.md.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";
import { supabase } from "../../lib/supabase";
import type {
  Extraction,
  FeeEntry,
  Listing,
  Override,
  ResolutionCandidate,
  UnitGroupState,
} from "./types";

type ListingResponse = components["schemas"]["ListingResponse"];
type ListingCreate = components["schemas"]["ListingCreate"];
type OverrideCreate = components["schemas"]["OverrideCreate"];
type OverrideResponse = components["schemas"]["OverrideResponse"];
type FeeEntryUpsert = components["schemas"]["FeeEntryUpsert"];
type FeeEntryResponse = components["schemas"]["FeeEntryResponse"];

const LISTING_SELECT =
  "*, property:properties(*, floor_plans(*), sources:property_sources(*)), scores(*)";

export function useListings(huntId: string) {
  return useQuery({
    queryKey: ["hunt_listings", huntId],
    queryFn: async (): Promise<Listing[]> => {
      const { data, error } = await supabase
        .from("hunt_listings")
        .select(LISTING_SELECT)
        .eq("hunt_id", huntId)
        .eq("property.floor_plans.is_current", true)
        .eq("status", "active");
      if (error) throw error;
      return (data ?? []) as unknown as Listing[];
    },
  });
}

export function useUnitGroupStates(huntId: string) {
  return useQuery({
    queryKey: ["listing_unit_group_states", huntId],
    queryFn: async (): Promise<UnitGroupState[]> => {
      const { data, error } = await supabase
        .from("listing_unit_group_states")
        .select("*, hunt_listing:hunt_listings!inner(hunt_id)")
        .eq("hunt_listing.hunt_id", huntId);
      if (error) throw error;
      return (data ?? []).map((record) => {
        const row = { ...record };
        Reflect.deleteProperty(row, "hunt_listing");
        return row;
      }) as UnitGroupState[];
    },
  });
}

export function usePatchUnitGroupState(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ listingId, unitGroupKey, interest_status, visited }: {
      listingId: string; unitGroupKey: string;
      interest_status: UnitGroupState["interest_status"]; visited: boolean;
    }) => apiFetch<UnitGroupState>(
      `/v1/listings/${listingId}/unit-groups/${unitGroupKey}/state`,
      { method: "PATCH", body: { interest_status, visited } },
    ),
    onSuccess: (saved) => {
      qc.setQueryData<UnitGroupState[]>(["listing_unit_group_states", huntId], (current = []) => [
        ...current.filter((state) => !(
          state.hunt_listing_id === saved.hunt_listing_id &&
          state.unit_group_key === saved.unit_group_key
        )),
        saved,
      ]);
      void qc.invalidateQueries({ queryKey: ["listing_unit_group_states", huntId] });
    },
  });
}

export function useOverrides(listingId: string) {
  return useQuery({
    queryKey: ["overrides", listingId],
    queryFn: async (): Promise<Override[]> => {
      const { data, error } = await supabase
        .from("current_overrides")
        .select("*")
        .eq("hunt_listing_id", listingId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as Override[];
    },
    enabled: Boolean(listingId),
  });
}

export function useFees(listingId: string) {
  return useQuery({
    queryKey: ["fee_checklist", listingId],
    queryFn: async (): Promise<FeeEntry[]> => {
      const { data, error } = await supabase
        .from("fee_checklist")
        .select("*")
        .eq("hunt_listing_id", listingId);
      if (error) throw error;
      return (data ?? []) as FeeEntry[];
    },
    enabled: Boolean(listingId),
  });
}

// Scoped resolved truth only. The view owns current identity; callers preserve
// concrete targets instead of flattening one row per Criterion.
export function useExtractions(propertyId: string, huntId: string) {
  return useQuery({
    queryKey: ["extractions", propertyId, huntId],
    queryFn: async (): Promise<Extraction[]> => {
      const { data, error } = await supabase
        .from("current_extractions")
        .select("*")
        .eq("property_id", propertyId)
        .or(`hunt_id.is.null,hunt_id.eq.${huntId}`)
        .order("extracted_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as Extraction[];
    },
    enabled: Boolean(propertyId),
  });
}

export function useProblematicPropertyIds(propertyIds: string[]) {
  const stableIds = [...new Set(propertyIds)].sort();
  return useQuery({
    queryKey: ["problematic-properties", stableIds],
    queryFn: async (): Promise<Set<string>> => {
      const { data, error } = await supabase
        .from("current_extractions")
        .select("property_id")
        .in("property_id", stableIds)
        .eq("disputed", true)
        .eq("resolution_rule", "conservative_disputed");
      if (error) throw error;
      return new Set((data ?? []).map((row) => row.property_id as string));
    },
    enabled: stableIds.length > 0,
  });
}

export function useResolutionCandidates(extractionId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["resolution-candidates", extractionId],
    queryFn: async (): Promise<ResolutionCandidate[]> => {
      const { data, error } = await supabase
        .from("extraction_resolution_candidates")
        .select(
          "selected,candidate:extractions!candidate_extraction_id(id,value,confidence,evidence_quote,source:property_sources(url,site_domain))",
        )
        .eq("resolution_extraction_id", extractionId);
      if (error) throw error;
      return (data ?? []).flatMap((edge) => {
        const candidate = Array.isArray(edge.candidate) ? edge.candidate[0] : edge.candidate;
        if (!candidate) return [];
        const source = Array.isArray(candidate.source) ? candidate.source[0] : candidate.source;
        return [
          {
            id: candidate.id as string,
            value: candidate.value,
            confidence: candidate.confidence as ResolutionCandidate["confidence"],
            evidence_quote: (candidate.evidence_quote as string | null) ?? null,
            selected: Boolean(edge.selected),
            source: source
              ? {
                  url: source.url as string,
                  site_domain: source.site_domain as string,
                }
              : null,
          },
        ];
      });
    },
    enabled: enabled && Boolean(extractionId),
  });
}

export function useCreateListing(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ListingCreate) =>
      apiFetch<ListingResponse>(`/v1/hunts/${huntId}/listings`, { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
      void qc.invalidateQueries({ queryKey: ["jobs", huntId] });
    },
  });
}

// Archived listings (m7): the same embed as the active query so buildRows
// works unchanged; fetched only while the Archived view is open.
export function useArchivedListings(huntId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["hunt_listings", huntId, "archived"],
    queryFn: async (): Promise<Listing[]> => {
      const { data, error } = await supabase
        .from("hunt_listings")
        .select(LISTING_SELECT)
        .eq("hunt_id", huntId)
        .eq("property.floor_plans.is_current", true)
        .eq("status", "archived");
      if (error) throw error;
      return (data ?? []) as unknown as Listing[];
    },
    enabled,
  });
}

// Archive/restore (m6/m7). Invalidating the ["hunt_listings", huntId] prefix
// refreshes both the active and archived queries.
export function usePatchListingStatus(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ listingId, status }: { listingId: string; status: "active" | "archived" }) =>
      apiFetch<ListingResponse>(`/v1/listings/${listingId}/status`, {
        method: "PATCH",
        body: { status } satisfies components["schemas"]["ListingStatusPatch"],
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] }),
  });
}

export function usePatchPins(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ listingId, pins }: { listingId: string; pins: Record<string, string> }) =>
      apiFetch<ListingResponse>(`/v1/listings/${listingId}/pins`, {
        method: "PATCH",
        body: { pins } satisfies components["schemas"]["PinsPatch"],
      }),
    onMutate: async ({ listingId, pins }) => {
      await qc.cancelQueries({ queryKey: ["hunt_listings", huntId] });
      const previous = qc.getQueryData<Listing[]>(["hunt_listings", huntId]);
      if (previous) {
        qc.setQueryData(
          ["hunt_listings", huntId],
          previous.map((listing) => (listing.id === listingId ? { ...listing, pins } : listing)),
        );
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(["hunt_listings", huntId], context.previous);
      }
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] }),
  });
}

export function usePatchSourcePolicy(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ listingId, sourcePolicy }: {
      listingId: string;
      sourcePolicy: Listing["source_policy"];
    }) => apiFetch<ListingResponse>(`/v1/listings/${listingId}/source-policy`, {
      method: "PATCH",
      body: { source_policy: sourcePolicy },
    }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
      void qc.invalidateQueries({ queryKey: ["jobs", huntId] });
    },
  });
}

export function useCreateOverride(huntId: string, listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OverrideCreate) =>
      apiFetch<OverrideResponse>(`/v1/listings/${listingId}/overrides`, { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["overrides", listingId] });
      // Rescore is async; the listings re-fetch picks up new scores when it lands.
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
    },
  });
}

export function useUpsertFee(huntId: string, listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slot, ...body }: FeeEntryUpsert & { slot: string }) =>
      apiFetch<FeeEntryResponse>(`/v1/listings/${listingId}/fees/${slot}`, {
        method: "PUT",
        body,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["fee_checklist", listingId] });
      void qc.invalidateQueries({ queryKey: ["hunt_listings", huntId] });
    },
  });
}

// P3-21 contact: the precedence-resolved winner per kind. The view already
// picked official site over Places over listing, so this reads at most two rows
// and never has to rank anything client-side.
export interface PropertyContact {
  kind: "phone" | "contact_url";
  value: string;
  provenance: "official_site" | "google_places" | "listing";
}

export function usePropertyContacts(propertyId: string) {
  return useQuery({
    queryKey: ["property_contacts", propertyId],
    queryFn: async (): Promise<PropertyContact[]> => {
      const { data, error } = await supabase
        .from("property_contacts_current")
        .select("kind, value, provenance")
        .eq("property_id", propertyId);
      if (error) throw error;
      return (data ?? []) as PropertyContact[];
    },
    enabled: Boolean(propertyId),
  });
}

// P3-7a gallery: property_images rows + short-lived signed URLs from the
// private `property-images` bucket (table RLS decides which paths we learn;
// the storage select policy lets authenticated users sign them).
export interface PropertyImage {
  id: string;
  url: string;
  width: number | null;
  height: number | null;
  kind?: "listing_photo" | "floor_plan_diagram" | "other";
  visionAssessment?: Record<string, unknown> | null;
  floorPlanAssociations?: string[];
}

export function usePropertyImages(propertyId: string) {
  return useQuery({
    queryKey: ["property_images", propertyId],
    queryFn: async (): Promise<PropertyImage[]> => {
      const { data, error } = await supabase
        .from("property_images")
        .select("id, storage_path, width, height, kind, vision_assessment")
        .eq("property_id", propertyId)
        .eq("is_current", true)
        .order("created_at", { ascending: true });
      if (error) throw error;
      const rows = data ?? [];
      if (rows.length === 0) return [];
      const { data: associations, error: associationError } = await supabase
        .from("current_floor_plan_images")
        .select("property_image_id, floor_plan_id")
        .in("property_image_id", rows.map((r) => r.id));
      if (associationError) throw associationError;
      const plansByImage = new Map<string, string[]>();
      for (const association of associations ?? []) {
        const plans = plansByImage.get(association.property_image_id) ?? [];
        plans.push(association.floor_plan_id);
        plansByImage.set(association.property_image_id, plans);
      }
      const { data: signed, error: signError } = await supabase.storage
        .from("property-images")
        .createSignedUrls(rows.map((r) => r.storage_path), 3600);
      if (signError) throw signError;
      const urlByPath = new Map((signed ?? []).map((s) => [s.path, s.signedUrl]));
      return rows.flatMap((row) => {
        const url = urlByPath.get(row.storage_path);
        return url
          ? [{
              id: row.id,
              url,
              width: row.width,
              height: row.height,
              kind: row.kind,
              visionAssessment: row.vision_assessment,
              floorPlanAssociations: plansByImage.get(row.id) ?? [],
            }]
          : [];
      });
    },
    enabled: Boolean(propertyId),
    staleTime: 45 * 60 * 1000, // refresh before the 1 h signature expires
  });
}
