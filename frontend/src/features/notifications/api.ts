import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import { useGhostMutationPath } from "../admin/useGhostMode";

export const NOTIFICATION_EVENTS = [
  "checkpoint_waiting",
  "run_failed",
  "listing_score_changed",
  "comment_added",
  "rating_changed",
] as const;
export type NotificationEvent = (typeof NOTIFICATION_EVENTS)[number];

export const NOTIFICATION_LABELS: Record<NotificationEvent, { label: string; description: string }> = {
  checkpoint_waiting: { label: "Checkpoint waiting", description: "A Listing run needs your answer." },
  run_failed: { label: "Run failed", description: "A Listing run you own, or an Owner watches, did not finish." },
  listing_score_changed: { label: "Listing score changed", description: "A completed run changed one or more Floor Plan scores." },
  comment_added: { label: "Comment added", description: "Another member commented on a Listing." },
  rating_changed: { label: "Rating changed", description: "Another member added or changed a Unit Group rating." },
};

export interface AccountNotificationPreferences {
  email: Record<NotificationEvent, boolean>;
}

export interface HuntNotificationPreferences {
  account_email: Record<NotificationEvent, boolean>;
  email_overrides: Record<NotificationEvent, boolean | null>;
  effective_email: Record<NotificationEvent, boolean>;
}

export interface HuntNotificationPreferenceUpdate {
  email_overrides: Record<NotificationEvent, boolean | null>;
}

export function useAccountNotificationPreferences() {
  return useQuery({
    queryKey: ["notification_preferences", "account"],
    queryFn: () => apiFetch<AccountNotificationPreferences>("/v1/notification-preferences"),
  });
}

export function useSaveAccountNotificationPreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AccountNotificationPreferences) =>
      apiFetch<AccountNotificationPreferences>("/v1/notification-preferences", {
        method: "PUT",
        body,
        demoResult: () => body,
      }),
    onSuccess: (saved) => {
      qc.setQueryData(["notification_preferences", "account"], saved);
      // Every inherited Hunt value is derived from these defaults. Mark all
      // cached Hunt preference views stale so navigation cannot show the old
      // effective setting after an account-level change.
      void qc.invalidateQueries({ queryKey: ["notification_preferences", "hunt"] });
    },
  });
}

export function useHuntNotificationPreferences(huntId: string) {
  return useQuery({
    queryKey: ["notification_preferences", "hunt", huntId],
    queryFn: () => apiFetch<HuntNotificationPreferences>(`/v1/hunts/${huntId}/notification-preferences`),
    enabled: Boolean(huntId),
  });
}

export function useSaveHuntNotificationPreferences(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: HuntNotificationPreferenceUpdate) =>
      apiFetch<HuntNotificationPreferences>(`/v1/hunts/${huntId}/notification-preferences`, {
        method: "PUT",
        body,
        demoResult: () => ({
          account_email: Object.fromEntries(
            NOTIFICATION_EVENTS.map((event) => [event, event === "checkpoint_waiting" || event === "run_failed"]),
          ) as Record<NotificationEvent, boolean>,
          email_overrides: body.email_overrides,
          effective_email: Object.fromEntries(
            NOTIFICATION_EVENTS.map((event) => [
              event,
              body.email_overrides[event] ?? (event === "checkpoint_waiting" || event === "run_failed"),
            ]),
          ) as Record<NotificationEvent, boolean>,
        }),
      }),
    onSuccess: (saved) => qc.setQueryData(["notification_preferences", "hunt", huntId], saved),
  });
}

export function useAttention(huntId: string) {
  const mutationPath = useGhostMutationPath(huntId);
  return useQuery({
    queryKey: ["attention", huntId],
    queryFn: () =>
      apiFetch<{
        waiting_checkpoint_count: number;
        failed: number;
        waiting_user: number;
        running: number;
        task_status: "failed" | "waiting_user" | "running" | null;
      }>(mutationPath(`/v1/hunts/${huntId}/attention`)),
    enabled: Boolean(huntId),
  });
}
