// Jobs data hooks (P1-13). The jobs list is THE one polled apiClient read
// (Phase 1 plan §1.6): refetchInterval 3000 against the active states; P2-4
// replaces the polling with Realtime. Assumptions: frontend/API_ASSUMPTIONS.md
// — including conflict #2: JobResponse must grow the parked checkpoint prompt.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";

export type JobState = components["schemas"]["JobState"];
export type JobType = components["schemas"]["JobType"];
export type Job = components["schemas"]["JobResponse"];

export const ACTIVE_STATES = "queued,running,waiting_user";

export function useActiveJobs(huntId: string) {
  return useQuery({
    queryKey: ["jobs", huntId, "active"],
    queryFn: () => apiFetch<Job[]>(`/v1/hunts/${huntId}/jobs?state=${ACTIVE_STATES}`),
    refetchInterval: 30000, // 30 seconds
  });
}

export function useJobs(huntId: string) {
  return useQuery({
    queryKey: ["jobs", huntId],
    queryFn: () => apiFetch<Job[]>(`/v1/hunts/${huntId}/jobs`),
    refetchInterval: 15000, // 15 seconds
  });
}

function useJobAction(huntId: string, action: "cancel" | "retry") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      apiFetch<Job>(`/v1/jobs/${jobId}/${action}`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["jobs", huntId] }),
  });
}

export function useCancelJob(huntId: string) {
  return useJobAction(huntId, "cancel");
}

export function useRetryJob(huntId: string) {
  return useJobAction(huntId, "retry");
}

// Checkpoint answer payload (§10.10): a chosen option, with free text when the
// option is the `other:<input>` form. The dict shape lands in jobs.payload —
// assumed contract, recorded in API_ASSUMPTIONS.md.
export function checkpointAnswer(choice: string, text?: string): { answer: Record<string, unknown> } {
  return { answer: text === undefined ? { choice } : { choice, text } };
}

export function useAnswerCheckpoint(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, choice, text }: { jobId: string; choice: string; text?: string }) =>
      apiFetch<Job>(`/v1/jobs/${jobId}/checkpoint`, {
        method: "POST",
        body: checkpointAnswer(choice, text),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["jobs", huntId] }),
  });
}
