// The Replay Capture bundle, and the pure functions that turn it into the rows
// the existing Tasks UI already knows how to render (DM-9, DESIGN §3, §16).
//
// The bundle is produced by `manzil export-demo-capture` from a real, finished
// ingest. Nothing here fabricates pipeline output: the events, the costs, the
// warnings and the finished Listing all come from a run that happened. What
// this module does is replay them in order, deriving the Job row at each step
// exactly as the worker would have written it — so `JobCard`, `PipelineTrack`
// and `CheckpointPromptCard` need no demo branch at all.

import type { Job, JobEvent } from "../../jobs/api";

export interface CaptureEvent {
  offset_ms: number;
  stage: string;
  event: string;
  detail: Record<string, unknown>;
}

export interface Capture {
  version: number;
  exported_at: string;
  source: {
    job_id: string;
    url: string | null;
    property_name: string | null;
    source_policy: string | null;
  };
  job: {
    type: string;
    cost_actual_usd: number;
    attempts: number;
    plan: Record<string, unknown> | null;
    warnings: { stage: string; code: string; message: string }[];
    real_duration_ms: number | null;
  };
  events: CaptureEvent[];
  has_checkpoint: boolean;
  listing: Record<string, unknown> & { id: string };
}

/**
 * The Job row as it stood after `count` events had been applied.
 *
 * Derived rather than recorded, for the same reason the worker derives it: two
 * sources for one row drift.
 *
 * Checkpoints animate through as ordinary timeline beats rather than parking
 * the run. Rendering a real prompt turned out to need either widening
 * `checkpoint_asked` to carry the full §10.10 shape — which a security review
 * showed could publish page excerpts and model-authored prose into
 * `capture.json`, a world-readable build artifact rather than something the
 * demo session gates — or a per-checkpoint-kind allow-list. Both are real work,
 * deferred (DESIGN §20 v3.58). A capture recorded from a Job that parked is
 * still usable: `checkpoint_asked`/`checkpoint_answered`/
 * `checkpoint_auto_resolved` are `completed`-shaped for state derivation, so
 * the run keeps moving rather than dead-ending with a prompt nobody renders.
 *
 * `stage_index` counts **distinct stage names seen in `completed` events**,
 * not `started` events: the ingest pipeline never emits `started`
 * (`postgres_persistence.py` writes it only for `rescore`/`refresh` Jobs), so
 * counting it left the pipeline track frozen at the first phase for every
 * demo capture. `completed` fires once per stage
 * (`postgres_persistence.py:136-138`) and is what `pipelinePhases.ts` needs to
 * disambiguate a repeated stage name (the second FETCH after DISCOVER).
 */
export function jobAt(capture: Capture, count: number, startedAtMs: number): Job {
  const applied = capture.events.slice(0, Math.max(0, count));
  const last = applied[applied.length - 1];
  const stagesCompleted = new Set(
    applied.filter((e) => e.event === "completed").map((e) => e.stage),
  ).size;

  const finished = applied.length === capture.events.length && capture.events.length > 0;

  const state: Job["state"] = finished ? "done" : applied.length === 0 ? "queued" : "running";

  // Cost accrues with the run rather than arriving whole at the end: per-run
  // spend is a first-class surface (FR10) and watching it tick up is part of
  // what the demo is showing.
  const progress = capture.events.length === 0 ? 0 : applied.length / capture.events.length;

  return {
    id: capture.source.job_id,
    hunt_listing_id: capture.listing.id,
    type: capture.job.type,
    state,
    current_stage: finished ? null : (last?.stage ?? null),
    stage_index: Math.max(0, stagesCompleted - 1),
    plan: capture.job.plan,
    attempts: capture.job.attempts,
    error: null,
    cost_actual_usd: Number((capture.job.cost_actual_usd * progress).toFixed(4)),
    created_at: new Date(startedAtMs).toISOString(),
    started_at: new Date(startedAtMs).toISOString(),
    finished_at: finished ? new Date(Date.now()).toISOString() : null,
    checkpoint: null,
    checkpoint_context: null,
    warnings: capture.job.warnings.slice(0, applied.length === 0 ? 0 : undefined),
  } as Job;
}

/** Capture events as `job_events` rows, for the History timeline. */
export function eventsAt(capture: Capture, count: number, startedAtMs: number): JobEvent[] {
  return capture.events.slice(0, Math.max(0, count)).map((event, index) => ({
    id: `demo-event-${index}`,
    job_id: capture.source.job_id,
    stage: event.stage,
    event: event.event,
    detail: event.detail,
    at: new Date(startedAtMs + event.offset_ms).toISOString(),
  }));
}

/** Index of the event that parks the run, or -1. */
export function checkpointIndex(capture: Capture): number {
  return capture.events.findIndex((e) => e.event === "checkpoint_asked");
}
