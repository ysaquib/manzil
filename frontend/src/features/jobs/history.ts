import dayjs from "dayjs";

import type { Job } from "./api";

export function jobStartTime(job: Pick<Job, "started_at" | "created_at">): string | null {
  const iso = job.started_at ?? job.created_at ?? null;
  if (!iso) return null;
  const start = dayjs(iso);
  if (!start.isValid()) return null;
  return start.format("MMM D, h:mm A");
}

export function jobDuration(job: Job): string | null {
  if (!job.created_at || !job.finished_at) return null;
  const milliseconds = Date.parse(job.finished_at) - Date.parse(job.created_at);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return null;
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

export function jobMeta(job: Job, memberName: string): string {
  const parts = [memberName];
  if (job.attempts > 1) parts.push(`attempt ${job.attempts}`);
  const start = jobStartTime(job);
  if (start) parts.push(start);
  const duration = jobDuration(job);
  if (duration) parts.push(duration);
  parts.push(formatJobCostUsd(job.cost_actual_usd));
  return parts.join(" · ");
}

export function filterHistoryJobs(
  jobs: Job[],
  filters: { listingId: string | null; memberId: string | null; outcome: string | null },
  addedByByListing: Map<string, string>,
): Job[] {
  return jobs.filter((job) => {
    if (filters.listingId && job.hunt_listing_id !== filters.listingId) return false;
    if (
      filters.memberId &&
      (!job.hunt_listing_id || addedByByListing.get(job.hunt_listing_id) !== filters.memberId)
    ) return false;
    if (filters.outcome && job.state !== filters.outcome) return false;
    return true;
  });
}

export function formatJobCostUsd(usd: number): string {
  return `$${Number(usd).toFixed(4)}`;
}

export function historySpendSummary(jobs: Job[]): { spendUsd: number; runCount: number } {
  return {
    spendUsd: jobs.reduce((sum, job) => sum + Number(job.cost_actual_usd ?? 0), 0),
    runCount: jobs.length,
  };
}

function runCountLabel(count: number): string {
  return `${count} run${count === 1 ? "" : "s"}`;
}

export function historySpendLabel(
  filtered: Job[],
  all: Job[],
  filtersActive: boolean,
): string {
  const filteredSummary = historySpendSummary(filtered);
  const allSummary = historySpendSummary(all);

  if (filtersActive) {
    return `${formatJobCostUsd(filteredSummary.spendUsd)} · ${runCountLabel(filteredSummary.runCount)} · ${formatJobCostUsd(allSummary.spendUsd)} total across ${runCountLabel(allSummary.runCount)}`;
  }
  return `Total spend: ${formatJobCostUsd(allSummary.spendUsd)} · ${runCountLabel(allSummary.runCount)}`;
}
