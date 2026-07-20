// Duplicate-submission pre-check (m3): before enqueueing a URL, look for a
// Property already in the hunt carrying it (official_url or any source URL).
// DEDUPE would merge them eventually, but the warning saves a whole pipeline
// run and a checkpoint. Pure and client-side over the already-loaded listings
// — a UX courtesy, not enforcement; "Submit anyway" always remains.
import type { Listing } from "./types";

/** Comparable form: host without www + path without trailing slash. */
export function normalizeListingUrl(url: string): string | null {
  try {
    const parsed = new URL(url.trim());
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const path = parsed.pathname.replace(/\/+$/, "");
    return `${host}${path}`;
  } catch {
    return null;
  }
}

/** The hunt Listing already carrying this URL, or null when it's new. */
export function findDuplicateListing(listings: Listing[], url: string): Listing | null {
  const target = normalizeListingUrl(url);
  if (target === null) return null;
  for (const listing of listings) {
    const known = [
      listing.property.official_url,
      ...listing.property.sources.map((source) => source.url),
    ];
    if (known.some((u) => u !== null && normalizeListingUrl(u) === target)) return listing;
  }
  return null;
}
