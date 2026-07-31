import type { QueryKey } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { supabase } from "./supabase";

export type HuntRealtimeTable =
  | "hunt_listings"
  | "scores"
  | "comments"
  | "ratings"
  | "listing_unit_group_states"
  | "hunt_listing_refresh_status"
  | "jobs"
  | "job_events"
  | "visits"
  | "visit_units"
  | "visit_entries"
  | "visit_defects"
  | "visit_custom_items"
  | "visit_fee_proposals";

export function invalidationKeysForRealtime(
  table: HuntRealtimeTable,
  huntId: string,
): QueryKey[] {
  switch (table) {
    case "hunt_listings":
    case "scores":
      return [["hunt_listings", huntId]];
    case "comments":
      return [["comments"], ["hunt_listings", huntId]];
    case "ratings":
      return [["ratings"]];
    case "listing_unit_group_states":
      return [["listing_unit_group_states", huntId]];
    case "hunt_listing_refresh_status":
      return [["hunt_listing_refresh_status", huntId]];
    case "jobs":
    case "job_events":
      return [["jobs", huntId]];
    // Visit rows carry no hunt_id of their own below `visits`, and one member
    // can be looking at a different Visit than the writer, so these invalidate
    // the whole family rather than one visit's keys. The list, the drawer's
    // per-Property list and the open Visit all hang off `visits`.
    // Cancelling a tour, or adding a door to one, changes the roll-up too.
    case "visits":
    case "visit_units":
      return [["visits", huntId], ["visit"], ["visit_unit_group_scores", huntId]];
    // An arriving answer can also open or close a fork (VC-6): the conflicts
    // view is derived from this table, so it goes stale on exactly the same
    // events and has no Realtime feed of its own.
    // An arriving rating also moves the Unit Group roll-up the Overview shows
    // (VC-8), and both views are derived from this table with no feed of their
    // own.
    case "visit_entries":
      return [["visit_entries"], ["visit_entry_conflicts"], ["visit_unit_group_scores", huntId]];
    case "visit_defects":
      return [["visit_defects"]];
    case "visit_custom_items":
      return [["visit_custom_items"]];
    // A decision here also changed a fee or an override on the Listing, so the
    // cost surfaces have to be told (VC-7).
    case "visit_fee_proposals":
      return [["visit_fee_proposals"], ["fee_checklist"], ["overrides"], ["hunt_listings", huntId]];
  }
}

export function useHuntRealtime(huntId: string | undefined): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!huntId) return;

    const invalidate = (table: HuntRealtimeTable) => {
      for (const queryKey of invalidationKeysForRealtime(table, huntId)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    };

    const channel = supabase
      .channel(`hunt:${huntId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "hunt_listings", filter: `hunt_id=eq.${huntId}` },
        () => invalidate("hunt_listings"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "scores" },
        () => invalidate("scores"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "comments" },
        () => invalidate("comments"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "ratings" },
        () => invalidate("ratings"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "listing_unit_group_states" },
        () => invalidate("listing_unit_group_states"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "hunt_listing_refresh_status" },
        () => invalidate("hunt_listing_refresh_status"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "jobs", filter: `hunt_id=eq.${huntId}` },
        () => invalidate("jobs"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "job_events" },
        () => invalidate("job_events"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "visits", filter: `hunt_id=eq.${huntId}` },
        () => invalidate("visits"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "visit_units" },
        () => invalidate("visit_units"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "visit_entries" },
        () => invalidate("visit_entries"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "visit_defects" },
        () => invalidate("visit_defects"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "visit_custom_items" },
        () => invalidate("visit_custom_items"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "visit_fee_proposals" },
        () => invalidate("visit_fee_proposals"),
      )
      .subscribe();

    return () => {
      void supabase.removeChannel(channel);
    };
  }, [huntId, queryClient]);
}
