// Jobs data hooks. P2-5 Realtime invalidates the shared ["jobs", huntId]
// query prefix; no polling remains.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";
import { supabase } from "../../lib/supabase";

export type JobState = components["schemas"]["JobState"];
export type JobType = components["schemas"]["JobType"];
export type Job = components["schemas"]["JobResponse"];

export const ACTIVE_STATES = "queued,running,waiting_user";
export const HISTORY_STATES = "done,failed,cancelled";

export function useActiveJobs(huntId: string) {
  return useQuery({
    queryKey: ["jobs", huntId, "active"],
    queryFn: () => apiFetch<Job[]>(`/v1/hunts/${huntId}/jobs?state=${ACTIVE_STATES}`),
  });
}

export function useJobs(huntId: string) {
  return useQuery({
    queryKey: ["jobs", huntId],
    queryFn: () => apiFetch<Job[]>(`/v1/hunts/${huntId}/jobs`),
  });
}

export function useHistoryJobs(huntId: string) {
  return useQuery({
    queryKey: ["jobs", huntId, "history"],
    queryFn: () => apiFetch<Job[]>(`/v1/hunts/${huntId}/jobs?state=${HISTORY_STATES}`),
  });
}

export interface JobEvent {
  id: string;
  job_id: string;
  stage: string;
  event: string;
  detail: Record<string, unknown>;
  at: string;
}

export function useJobEvents(jobId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["job_events", jobId],
    queryFn: async (): Promise<JobEvent[]> => {
      const { data, error } = await supabase
        .from("job_events")
        .select("*")
        .eq("job_id", jobId)
        .order("at");
      if (error) throw error;
      return (data ?? []) as JobEvent[];
    },
    enabled,
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
