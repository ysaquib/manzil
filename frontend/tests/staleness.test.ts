import { describe, expect, it } from "vitest";

import { staleRefreshClasses, statusesByListing } from "../src/features/listings/staleness";
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
  it("uses the 24-hour pricing boundary exactly", () => {
    expect(
      staleRefreshClasses(
        [status("pricing", "2026-07-28T12:00:00Z")],
        NOW,
      ),
    ).toEqual(["pricing"]);
    expect(
      staleRefreshClasses(
        [status("pricing", "2026-07-28T12:00:01Z")],
        NOW,
      ),
    ).toEqual([]);
  });

  it("uses 14 days for listing details and 30 days for images/reviews", () => {
    expect(
      staleRefreshClasses(
        [
          status("listing_details", "2026-07-15T12:00:00Z"),
          status("images", "2026-06-29T12:00:00Z"),
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
        status("pricing", "2026-07-28T11:59:00Z", "one"),
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
});
