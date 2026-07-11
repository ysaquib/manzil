import type { QueryKey } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { supabase } from "./supabase";

export type HuntRealtimeTable =
  | "hunt_listings"
  | "scores"
  | "comments"
  | "jobs"
  | "job_events";

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
    case "jobs":
    case "job_events":
      return [["jobs", huntId]];
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
        { event: "*", schema: "public", table: "jobs", filter: `hunt_id=eq.${huntId}` },
        () => invalidate("jobs"),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "job_events" },
        () => invalidate("job_events"),
      )
      .subscribe();

    return () => {
      void supabase.removeChannel(channel);
    };
  }, [huntId, queryClient]);
}
