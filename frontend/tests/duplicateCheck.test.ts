import { describe, expect, it } from "vitest";

import { findDuplicateListing, normalizeListingUrl } from "../src/features/listings/duplicateCheck";
import type { Listing, PropertySource } from "../src/features/listings/types";

function makeListing(id: string, official: string | null, sourceUrls: string[] = []): Listing {
  const sources = sourceUrls.map(
    (url, i): PropertySource => ({
      id: `${id}-src-${i}`,
      property_id: `${id}-prop`,
      url,
      site_domain: new URL(url).hostname,
      is_official: false,
      last_fetched_at: null,
      last_success_at: null,
    }),
  );
  return {
    id,
    hunt_id: "hunt-1",
    property_id: `${id}-prop`,
    added_by: "user-1",
    status: "active",
    source_policy: "tiers_1_2_3",
    single_source_reason: null,
    pins: {},
    created_at: "2026-07-19T00:00:00Z",
    unavailable_at: null,
    all_in_components: null,
    property: {
      id: `${id}-prop`,
      name: `Property ${id}`,
      canonical_address: "1 Main St",
      city: null,
      state: null,
      county: null,
      official_url: official,
      lat: null,
      lng: null,
      floor_plans: [],
      sources,
    },
    scores: [],
  };
}

describe("normalizeListingUrl", () => {
  it("strips www, trailing slashes, query, and case on the host", () => {
    expect(normalizeListingUrl("https://WWW.Example.com/apts/")).toBe("example.com/apts");
    expect(normalizeListingUrl("http://example.com/apts?utm=x#top")).toBe("example.com/apts");
  });

  it("returns null for garbage", () => {
    expect(normalizeListingUrl("not a url")).toBeNull();
  });
});

describe("findDuplicateListing", () => {
  const listings = [
    makeListing("l1", "https://www.maple-court.example/floorplans"),
    makeListing("l2", null, ["https://aggregator.example/listings/oak-ridge/"]),
  ];

  it("matches the official URL and any source URL despite cosmetic differences", () => {
    expect(
      findDuplicateListing(listings, "https://maple-court.example/floorplans/")?.id,
    ).toBe("l1");
    expect(
      findDuplicateListing(listings, "https://AGGREGATOR.example/listings/oak-ridge")?.id,
    ).toBe("l2");
  });

  it("returns null for new URLs and unparseable input", () => {
    expect(findDuplicateListing(listings, "https://maple-court.example/contact")).toBeNull();
    expect(findDuplicateListing(listings, "nope")).toBeNull();
  });
});
