// Feedback submission (P3-16). One mutation; nothing is read back — the table
// is insert-only by design (DESIGN §20 v3.27), so there is no list to
// invalidate and no query key here.
import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";

export const FEEDBACK_CATEGORIES = [
  { value: "bug", label: "Bug" },
  { value: "feature", label: "Feature request" },
  { value: "confusing", label: "Confusing" },
  { value: "wrong_data", label: "Wrong data" },
  { value: "other", label: "Something else" },
] as const;

export type FeedbackCategory = (typeof FEEDBACK_CATEGORIES)[number]["value"];

export interface FeedbackDraft {
  category: FeedbackCategory;
  body: string;
  route: string | null;
  hunt_id: string | null;
  app_version: string | null;
}

export interface FeedbackReceipt {
  id: string;
  created_at: string;
}

export function appVersion(): string | null {
  return (import.meta.env.VITE_APP_VERSION as string | undefined) ?? null;
}

export function useSubmitFeedback() {
  return useMutation({
    mutationFn: (draft: FeedbackDraft) =>
      apiFetch<FeedbackReceipt>("/v1/feedback", { method: "POST", body: draft }),
  });
}
