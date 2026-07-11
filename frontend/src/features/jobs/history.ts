import type { Job } from "./api";

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
