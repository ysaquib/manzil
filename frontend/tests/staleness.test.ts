import { describe, expect, it } from "vitest";

import {
  hasRetryableImageFetchPartial,
  listingNeedsImageRefresh,
  showRefreshImagesAction,
  staleRefreshClasses,
  statusesByListing,
} from "../src/features/listings/staleness";
import type { RefreshStatus } from "../src/features/listings/types";

const NOW = Date.parse("2026-07-29T12:00:00Z");

function status(
  refresh_class: RefreshStatus["refresh_class"],
  last_success_at: string,
  hunt_listing_id = "listing-a",
): RefreshStatus {
  return {
    hunt_listing_id,
    refresh_class,
    last_success_at,
    producer_job_id: null,
  };
}

describe("refresh staleness", () => {
  it("uses the 10-day pricing boundary exactly", () => {
    expect(
      staleRefreshClasses(
        [status("pricing", "2026-07-19T12:00:00Z")],
        NOW,
      ),
    ).toEqual(["pricing"]);
    expect(
      staleRefreshClasses(
        [status("pricing", "2026-07-19T12:00:01Z")],
        NOW,
      ),
    ).toEqual([]);
  });

  it("uses 30 days for listing details/reviews and 60 days for images", () => {
    expect(
      staleRefreshClasses(
        [
          status("listing_details", "2026-06-29T12:00:00Z"),
          status("images", "2026-05-30T12:00:00Z"),
          status("reviews", "2026-06-29T12:00:01Z"),
          status("location", "2020-01-01T00:00:00Z"),
        ],
        NOW,
      ),
    ).toEqual(["listing_details", "images"]);
  });

  it("groups stale classes per Listing", () => {
    const grouped = statusesByListing(
      [
        status("pricing", "2026-07-19T11:59:00Z", "one"),
        status("pricing", "2026-07-29T11:59:00Z", "two"),
      ],
      NOW,
    );
    expect(grouped.get("one")).toEqual(["pricing"]);
    expect(grouped.get("two")).toEqual([]);
  });

  it("treats missing required text-class markers as stale", () => {
    const grouped = statusesByListing(
      [status("pricing", "2026-07-29T11:59:00Z", "one")],
      NOW,
      ["one", "two"],
    );
    expect(grouped.get("one")).toEqual(["listing_details"]);
    expect(grouped.get("two")).toEqual(["pricing", "listing_details"]);
  });

  it("treats a missing or expired images marker as needing image refresh", () => {
    const now = NOW;
    expect(
      listingNeedsImageRefresh(
        [status("pricing", "2026-07-29T11:59:00Z", "one")],
        "one",
        now,
      ),
    ).toBe(true);
    expect(
      listingNeedsImageRefresh(
        [
          status("images", "2026-05-30T12:00:00Z", "one"),
          status("pricing", "2026-07-29T11:59:00Z", "one"),
        ],
        "one",
        now,
      ),
    ).toBe(true);
    expect(
      listingNeedsImageRefresh(
        [
          status("images", "2026-05-30T12:00:01Z", "one"),
          status("pricing", "2026-07-29T11:59:00Z", "one"),
        ],
        "one",
        now,
      ),
    ).toBe(false);
  });

  it("shows the images action for retryable partial fetches but not cap-saturated ones", () => {
    const partialJob = {
      hunt_listing_id: "listing-a",
      state: "done",
      finished_at: "2026-07-29T12:00:00Z",
      warnings: [{ code: "image_fetch_partial", detail: { cap_saturated: false } }],
    };
    const saturatedJob = {
      hunt_listing_id: "listing-a",
      state: "done",
      finished_at: "2026-07-29T13:00:00Z",
      warnings: [{ code: "image_fetch_partial", detail: { cap_saturated: true } }],
    };
    expect(hasRetryableImageFetchPartial([partialJob], "listing-a")).toBe(true);
    expect(hasRetryableImageFetchPartial([saturatedJob], "listing-a")).toBe(false);
    expect(
      showRefreshImagesAction(
        [status("images", "2026-05-30T12:00:01Z", "listing-a")],
        "listing-a",
        [saturatedJob],
        NOW,
      ),
    ).toBe(false);
  });
});
