import { describe, expect, it } from "vitest";

import {
  buildMapPoints,
  markerArt,
  pinColorTokens,
  pinSummary,
  svgDataUri,
} from "../src/features/map/mapPoints";
import { buildRows } from "../src/features/listings/overviewRows";
import type { FloorPlan, Listing, Score } from "../src/features/listings/types";

function makeListing(
  id: string,
  name: string,
  plans: Partial<FloorPlan>[],
  totals: Record<string, number> = {},
  coords: { lat: number | null; lng: number | null } = { lat: 42.3, lng: -83.1 },
): Listing {
  const floorPlans = plans.map(
    (p, i): FloorPlan => ({
      id: `${id}-plan-${i}`,
      property_id: `${id}-prop`,
      source_id: "src",
      plan_name: `Plan ${i}`,
      beds: 2,
      baths: 2,
      sqft_min: null,
      sqft_max: null,
      rent_min: null,
      rent_max: null,
      deposit: null,
      availability_date: null,
      available_units: null,
      ...p,
    }),
  );
  const scores = Object.entries(totals).map(
    ([planId, total]): Score => ({
      hunt_listing_id: id,
      floor_plan_id: planId,
      total,
      breakdown: { base: 10, total, rubric_version: 1, clamped: false, gates: [], criteria: [] },
      rubric_version: 1,
      computed_at: "2026-07-08T00:00:00Z",
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
    created_at: "2026-07-08T00:00:00Z",
    unavailable_at: null,
    all_in_components: null,
    property: {
      id: `${id}-prop`,
      name,
      canonical_address: "1 Main St",
      city: null,
      state: null,
      county: null,
      official_url: null,
      lat: coords.lat,
      lng: coords.lng,
      floor_plans: floorPlans,
      sources: [],
    },
    scores,
  };
}

describe("buildMapPoints", () => {
  it("collapses a listing's unit groups into one pin, best score first", () => {
    const listing = makeListing(
      "l1",
      "Beta Flats",
      [
        { beds: 1, baths: 1 },
        { beds: 2, baths: 2 },
      ],
      { "l1-plan-0": 4, "l1-plan-1": 9 },
    );
    const { points, omissions } = buildMapPoints(buildRows([listing]));
    expect(points).toHaveLength(1);
    expect(points[0].groups.map((g) => g.label)).toEqual(["2 bd / 2 ba", "1 bd / 1 ba"]);
    expect(points[0].bestScore).toBe(9);
    expect(omissions).toEqual({ unmapped: 0, unscored: 0 });
  });

  it("keeps only the scored groups a pin represents", () => {
    const listing = makeListing(
      "l1",
      "Mixed",
      [
        { beds: 1, baths: 1 },
        { beds: 2, baths: 2 },
      ],
      { "l1-plan-1": 8 },
    );
    const { points } = buildMapPoints(buildRows([listing]));
    expect(points[0].groups).toHaveLength(1);
    expect(points[0].groups[0].label).toBe("2 bd / 2 ba");
  });

  it("counts a scored listing with no geocode as unmapped, not as a pin", () => {
    const listing = makeListing("l1", "No Geocode", [{ beds: 2, baths: 2 }], { "l1-plan-0": 8 }, {
      lat: null,
      lng: null,
    });
    const { points, omissions } = buildMapPoints(buildRows([listing]));
    expect(points).toHaveLength(0);
    expect(omissions.unmapped).toBe(1);
    expect(omissions.unscored).toBe(0);
  });

  it("counts a mapped but unscored listing as unscored", () => {
    const listing = makeListing("l1", "Pending", [{ beds: 2, baths: 2 }]);
    const { points, omissions } = buildMapPoints(buildRows([listing]));
    expect(points).toHaveLength(0);
    expect(omissions.unscored).toBe(1);
  });

  it("paints the best-scoring property last so it lands on top", () => {
    const rows = buildRows([
      makeListing("l1", "Weak", [{ beds: 2, baths: 2 }], { "l1-plan-0": 3 }),
      makeListing("l2", "Strong", [{ beds: 2, baths: 2 }], { "l2-plan-0": 10 }),
    ]);
    const { points } = buildMapPoints(rows);
    expect(points.map((p) => p.propertyName)).toEqual(["Weak", "Strong"]);
  });
});

describe("pinColorTokens", () => {
  it("de-duplicates same-band groups into one solid color", () => {
    const listing = makeListing(
      "l1",
      "Same Band",
      [
        { beds: 1, baths: 1 },
        { beds: 2, baths: 2 },
      ],
      { "l1-plan-0": 10, "l1-plan-1": 10 },
    );
    const { points } = buildMapPoints(buildRows([listing]));
    expect(pinColorTokens(points[0].groups)).toHaveLength(1);
  });

  it("keeps one color per distinct band, best first", () => {
    const listing = makeListing(
      "l1",
      "Split",
      [
        { beds: 1, baths: 1 },
        { beds: 2, baths: 2 },
      ],
      { "l1-plan-0": 2, "l1-plan-1": 10 },
    );
    const { points } = buildMapPoints(buildRows([listing]));
    const tokens = pinColorTokens(points[0].groups);
    expect(tokens).toHaveLength(2);
    expect(tokens[0]).toBe("scoreHighest");
  });
});

describe("pinSummary", () => {
  it("names the group for a single-group pin", () => {
    const listing = makeListing("l1", "One", [{ beds: 2, baths: 2 }], { "l1-plan-0": 9.5 });
    const { points } = buildMapPoints(buildRows([listing]));
    expect(pinSummary(points[0].groups)).toBe("2 bd / 2 ba · 9.5");
  });

  it("ranges the scores for a multi-group pin", () => {
    const listing = makeListing(
      "l1",
      "Two",
      [
        { beds: 1, baths: 1 },
        { beds: 2, baths: 2 },
      ],
      { "l1-plan-0": 4, "l1-plan-1": 9 },
    );
    const { points } = buildMapPoints(buildRows([listing]));
    expect(pinSummary(points[0].groups)).toBe("2 unit groups · 4–9");
  });
});

/** Pull the `viewBox` out of a marker SVG as [minX, minY, width, height]. */
function viewBox(svg: string): [number, number, number, number] {
  const match = svg.match(/viewBox="(-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)"/);
  if (!match) throw new Error("no viewBox");
  return [+match[1], +match[2], +match[3], +match[4]];
}

/** The silhouette path's `d`, which ends by running down to the tip. */
function silhouette(svg: string): string {
  const match = svg.match(/<clipPath id="[^"]+"><path d="([^"]+)"/);
  if (!match) throw new Error("no silhouette");
  return match[1];
}

/** The `y` of the point, read off the silhouette's closing line-to. */
function tipY(svg: string): number {
  const match = silhouette(svg).match(/L 0 ([\d.]+) Z$/);
  if (!match) throw new Error("silhouette does not end at a tip");
  return +match[1];
}

/** Fill colors used by the slice paths, in paint order. */
function fills(svg: string): string[] {
  return [...svg.matchAll(/<path d="[^"]+" fill="(#[0-9a-f]{6})" \/>/gi)].map((m) => m[1]);
}

describe("markerArt", () => {
  it("fills a solid pin with its one color", () => {
    const art = markerArt(["#111111"], { outline: "#ffffff" });
    expect(fills(art.svg)).toEqual(["#111111"]);
  });

  it("slices once per color, best band first", () => {
    const art = markerArt(["#111111", "#222222", "#333333"], { outline: "#ffffff" });
    expect(fills(art.svg)).toEqual(["#111111", "#222222", "#333333"]);
  });

  // Regression: slices used to be drawn at the head's radius, so the point
  // kept the first band's color and an arc read as a bite across the neck.
  // They are now oversized and clipped, so a slice can reach the tip.
  it("clips oversized slices to the silhouette so the point is colored too", () => {
    const art = markerArt(["#111111", "#222222"], { outline: "#ffffff" });
    const clipId = art.svg.match(/<clipPath id="([^"]+)"/)?.[1];
    expect(clipId).toBeTruthy();
    expect(art.svg).toContain(`clip-path="url(#${clipId})"`);
    // Every slice must reach past the tip, or clipping would leave a gap.
    const clipped = art.svg.match(/<g clip-path="[^"]+">(.*)<\/g>/)?.[1] ?? "";
    const reach = [...clipped.matchAll(/A (\d+(?:\.\d+)?) \1 0/g)].map((m) => +m[1]);
    expect(reach.length).toBeGreaterThan(0);
    for (const radius of reach) expect(radius).toBeGreaterThanOrEqual(tipY(art.svg));
  });

  // Regression: the viewBox was once shorter than the stem, so the point was
  // clipped clean off and only the head rendered.
  it.each([1, 2, 3, 4])("keeps the whole stem inside the viewBox with %i colors", (count) => {
    const art = markerArt(Array.from({ length: count }, () => "#111111"), {
      outline: "#ffffff",
    });
    const [, minY, , height] = viewBox(art.svg);
    expect(tipY(art.svg)).toBeLessThanOrEqual(minY + height);
  });

  it("anchors at the tip rather than the bottom edge of the artwork", () => {
    const art = markerArt(["#111111"], { outline: "#ffffff" });
    const [, minY, , height] = viewBox(art.svg);
    expect(art.anchorX).toBe(art.width / 2);
    expect(art.anchorY).toBeCloseTo(((tipY(art.svg) - minY) / height) * art.height, 6);
    // Padding below the point means the anchor is inside, not on, the edge.
    expect(art.anchorY).toBeLessThan(art.height);
  });

  // Every pin is the same object with different fills: no hub dot, badge, or
  // other decoration that would make a sliced pin read as a different kind of
  // marker than a solid one.
  it("gives solid and sliced pins the same silhouette, size, and anchor", () => {
    const solid = markerArt(["#111111"], { outline: "#ffffff" });
    const sliced = markerArt(["#111111", "#222222"], { outline: "#ffffff" });
    expect(sliced.width).toBe(solid.width);
    expect(sliced.height).toBe(solid.height);
    expect(sliced.anchorY).toBe(solid.anchorY);
    expect(silhouette(sliced.svg)).toBe(silhouette(solid.svg));
    // The only element a sliced pin adds is the divider between bands —
    // never a dot or badge that a solid pin lacks.
    const tags = (svg: string) => [...new Set(svg.match(/<[a-z]+/g) ?? [])].sort();
    expect(tags(sliced.svg)).toEqual([...tags(solid.svg), "<line"].sort());
  });

  it("scales up when selected, anchor included", () => {
    const plain = markerArt(["#111111"], { outline: "#fff" });
    const selected = markerArt(["#111111"], { outline: "#fff", selected: true });
    expect(selected.width).toBeGreaterThan(plain.width);
    expect(selected.anchorY / selected.height).toBeCloseTo(plain.anchorY / plain.height, 6);
  });
});

describe("svgDataUri", () => {
  it("percent-encodes the payload so it survives an img src", () => {
    expect(svgDataUri('<svg fill="#fff"/>')).toBe(
      "data:image/svg+xml;charset=UTF-8,%3Csvg%20fill%3D%22%23fff%22%2F%3E",
    );
  });
});
