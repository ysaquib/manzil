// Pipeline state for an Overview row (UI Decision Log 2026-07-26): is this
// listing still being worked on, or did its last run fail?
//
// Jobs join to listings through `JobResponse.hunt_listing_id`. A listing with
// no job at all has no pipeline state — it falls through to the existing
// "Pending" / "No availability" treatment rather than reading as failed.
//
// The blanked, hand-off row layout is reserved for rows that have nothing to
// show yet (`row.group === null`). A listing that already scored and is being
// refreshed keeps every value and only swaps its marker — losing the data you
// already have because a background refresh is running would be a regression.
import type { Job } from "../jobs/api";
import type { OverviewRow } from "./overviewRows";

export type PipelineState = "working" | "failed";

export interface RowPipeline {
  state: PipelineState;
  /** Stage name while working, error text when failed; may be null. */
  detail: string | null;
  jobId: string;
  /** True when the row has no data of its own, so the cells stand in as a hand-off. */
  placeholder: boolean;
}

const ACTIVE: ReadonlySet<string> = new Set(["queued", "running", "waiting_user"]);

/** Latest job per listing, newest first by created_at. */
export function jobsByListing(jobs: Job[]): Map<string, Job[]> {
  const byListing = new Map<string, Job[]>();
  for (const job of jobs) {
    if (!job.hunt_listing_id) continue;
    const bucket = byListing.get(job.hunt_listing_id);
    if (bucket) bucket.push(job);
    else byListing.set(job.hunt_listing_id, [job]);
  }
  for (const bucket of byListing.values()) {
    bucket.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }
  return byListing;
}

export function rowPipelineState(
  row: OverviewRow,
  byListing: Map<string, Job[]>,
): RowPipeline | null {
  const jobs = byListing.get(row.listing.id);
  if (!jobs || jobs.length === 0) return null;
  const placeholder = row.group === null;

  // An in-flight run outranks a past failure: the row is moving again.
  const active = jobs.find((job) => ACTIVE.has(job.state));
  if (active) {
    return {
      state: "working",
      detail: active.current_stage,
      jobId: active.id,
      placeholder,
    };
  }

  const latest = jobs[0];
  if (latest.state === "failed") {
    return { state: "failed", detail: latest.error, jobId: latest.id, placeholder };
  }
  return null;
}
