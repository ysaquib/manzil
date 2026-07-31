// Jobs data hooks. P2-5 Realtime invalidates the shared ["jobs", huntId]
// query prefix; no polling remains.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";
import { supabase } from "../../lib/supabase";

export type JobState = components["schemas"]["JobState"];
export type JobType = components["schemas"]["JobType"];
// started_at is intersected until the next `pnpm gen:api-types` run picks it
// up from the API's JobResponse (added for the running-job elapsed timer).
// A non-fatal degradation a stage recorded (API `JobWarning`, worker
// `StageWarning`): the run kept going, but it wants a human to know.
export interface JobWarning {
  stage: string;
  code: string;
  message: string;
  detail?: Record<string, unknown>;
}

export interface CheckpointEvidence {
  value?: unknown;
  evidence_quote?: string | null;
  source_url?: string | null;
}

export interface CheckpointContext {
  source_url?: string | null;
  evidence?: CheckpointEvidence[];
}

export interface AutoResolvedCheckpoint {
  prompt: components["schemas"]["CheckpointPrompt"];
  answer: Record<string, unknown>;
  resolved_at: string;
  context: CheckpointContext;
  corrected_at?: string | null;
  correction_job_id?: string | null;
}

// started_at, stage_index, and warnings are intersected until the next
// `pnpm gen:api-types` run picks them up from the API's JobResponse.
export type Job = components["schemas"]["JobResponse"] & {
  started_at?: string | null;
  stage_index?: number | null;
  warnings?: JobWarning[];
  checkpoint_context?: CheckpointContext | null;
  auto_resolved_checkpoint?: AutoResolvedCheckpoint | null;
};

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
