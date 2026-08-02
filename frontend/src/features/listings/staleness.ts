import type { RefreshClass, RefreshStatus } from "./types";

export const REFRESH_TTL_MS: Record<Exclude<RefreshClass, "location">, number> = {
  pricing: 24 * 60 * 60 * 1000,
  listing_details: 14 * 24 * 60 * 60 * 1000,
  images: 30 * 24 * 60 * 60 * 1000,
  reviews: 30 * 24 * 60 * 60 * 1000,
};

export function staleRefreshClasses(
  statuses: RefreshStatus[],
  now = Date.now(),
): RefreshClass[] {
  return statuses.flatMap((status) => {
    if (status.refresh_class === "location") return [];
    const ttl = REFRESH_TTL_MS[status.refresh_class];
    return now - new Date(status.last_success_at).getTime() >= ttl
      ? [status.refresh_class]
      : [];
  });
}

/** True when the Listing has no images marker or the 30-day images TTL has elapsed. */
export function listingNeedsImageRefresh(
  statuses: RefreshStatus[],
  listingId: string,
  now = Date.now(),
): boolean {
  const rows = statuses.filter((status) => status.hunt_listing_id === listingId);
  const images = rows.find((status) => status.refresh_class === "images");
  if (!images) return true;
  return staleRefreshClasses(rows, now).includes("images");
}

interface ImageFetchJobHint {
  hunt_listing_id: string | null;
  state: string;
  finished_at?: string | null;
  warnings?: { code: string; detail?: Record<string, unknown> }[];
}

/** Latest done Job still reporting a retryable underfilled partial image fetch. */
export function hasRetryableImageFetchPartial(
  jobs: ImageFetchJobHint[],
  listingId: string,
): boolean {
  const latest = jobs
    .filter((job) => job.hunt_listing_id === listingId && job.state === "done")
    .sort(
      (left, right) =>
        Date.parse(right.finished_at ?? "") - Date.parse(left.finished_at ?? ""),
    )[0];
  return (
    latest?.warnings?.some(
      (warning) =>
        warning.code === "image_fetch_partial" && warning.detail?.cap_saturated !== true,
    ) ?? false
  );
}

export function showRefreshImagesAction(
  statuses: RefreshStatus[],
  listingId: string,
  jobs: ImageFetchJobHint[] = [],
  now = Date.now(),
): boolean {
  return (
    listingNeedsImageRefresh(statuses, listingId, now)
    || hasRetryableImageFetchPartial(jobs, listingId)
  );
}

export function statusesByListing(
  statuses: RefreshStatus[],
  now = Date.now(),
  listingIds: string[] = [],
): Map<string, RefreshClass[]> {
  const grouped = new Map<string, RefreshStatus[]>();
  for (const listingId of listingIds) grouped.set(listingId, []);
  for (const status of statuses) {
    grouped.set(status.hunt_listing_id, [
      ...(grouped.get(status.hunt_listing_id) ?? []),
      status,
    ]);
  }
  return new Map(
    [...grouped].map(([listingId, rows]) => {
      const stale = new Set(staleRefreshClasses(rows, now));
      if (listingIds.includes(listingId)) {
        const present = new Set(rows.map((row) => row.refresh_class));
        if (!present.has("pricing")) stale.add("pricing");
        if (!present.has("listing_details")) stale.add("listing_details");
      }
      return [listingId, [...stale]];
    }),
  );
}
