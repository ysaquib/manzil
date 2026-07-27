// Map point derivation and marker artwork (§13.2 map surfaces). Pure and
// unit-tested; the map components stay declarative and only own the imperative
// Google Maps calls.
//
// One pin is one *Listing* — Unit Groups of the same property share a building,
// so they share a coordinate. The pin carries every scored Unit Group the
// caller's filters kept, which is why clicking a multi-group pin has to ask
// which group the user meant before opening the drawer.
import { scoreColor, formatScore } from "../listings/scoreBands";
import type { OverviewRow } from "../listings/overviewRows";
import { unitGroupLabel } from "../listings/unitGroups";

export interface MapGroup {
  /** pin key, `"{beds}-{baths}"` (§8.2) */
  key: string;
  label: string;
  score: number;
  /** Mantine theme token (`scoreHigh`, …) — resolved to a hex at paint time. */
  colorToken: string;
  rentMin: number | null;
  rentMax: number | null;
  planCount: number;
}

export interface MapPoint {
  listingId: string;
  propertyName: string;
  address: string;
  lat: number;
  lng: number;
  /** Scored Unit Groups, best score first. Never empty. */
  groups: MapGroup[];
  bestScore: number;
}

/** Why visible rows did not become pins — rendered as an honest footnote. */
export interface MapOmissions {
  /** Listings with scored groups but no geocode yet (§12 forever-cache). */
  unmapped: number;
  /** Listings that are mapped but have no scored Unit Group yet. */
  unscored: number;
}

export interface MapPointsResult {
  points: MapPoint[];
  omissions: MapOmissions;
}

function hasCoords(
  property: { lat: number | null; lng: number | null },
): property is { lat: number; lng: number } {
  return (
    typeof property.lat === "number" &&
    typeof property.lng === "number" &&
    Number.isFinite(property.lat) &&
    Number.isFinite(property.lng)
  );
}

/**
 * Collapse Overview rows (one per Unit Group) into one pin per Listing.
 * Rows arrive already filtered and sorted, so the map and the table always
 * agree about what is in view.
 */
export function buildMapPoints(rows: OverviewRow[]): MapPointsResult {
  const byListing = new Map<string, { row: OverviewRow; groups: MapGroup[] }>();

  for (const row of rows) {
    let entry = byListing.get(row.listing.id);
    if (!entry) {
      entry = { row, groups: [] };
      byListing.set(row.listing.id, entry);
    }
    const score = row.group?.displayScore;
    if (!row.group || !score) continue;
    entry.groups.push({
      key: row.group.key,
      label: unitGroupLabel(row.group.beds, row.group.baths),
      score: score.total,
      colorToken: scoreColor(score.total),
      rentMin: row.group.rentMin,
      rentMax: row.group.rentMax,
      planCount: row.group.plans.length,
    });
  }

  const points: MapPoint[] = [];
  const omissions: MapOmissions = { unmapped: 0, unscored: 0 };

  for (const { row, groups } of byListing.values()) {
    const property = row.listing.property;
    if (groups.length === 0) {
      omissions.unscored += 1;
      continue;
    }
    if (!hasCoords(property)) {
      omissions.unmapped += 1;
      continue;
    }
    groups.sort((a, b) => b.score - a.score);
    points.push({
      listingId: row.listing.id,
      propertyName: property.name,
      address: property.canonical_address,
      lat: property.lat,
      lng: property.lng,
      groups,
      bestScore: groups[0].score,
    });
  }

  // Best last so the strongest match paints on top of its neighbours.
  points.sort((a, b) => a.bestScore - b.bestScore);
  return { points, omissions };
}

/**
 * The distinct band colors a pin must show, best score first. A property whose
 * Unit Groups score into different bands shows every one of them — averaging
 * them would invent a score nobody computed.
 */
export function pinColorTokens(groups: MapGroup[]): string[] {
  const seen: string[] = [];
  for (const group of groups) {
    if (!seen.includes(group.colorToken)) seen.push(group.colorToken);
  }
  return seen;
}

/** Summary line under a pin's title: "3 unit groups · 9.5–6" or "2 bd / 2 ba". */
export function pinSummary(groups: MapGroup[]): string {
  if (groups.length === 1) return `${groups[0].label} · ${formatScore(groups[0].score)}`;
  const best = formatScore(groups[0].score);
  const worst = formatScore(groups[groups.length - 1].score);
  const range = best === worst ? best : `${worst}–${best}`;
  return `${groups.length} unit groups · ${range}`;
}

// ── Marker artwork ─────────────────────────────────────────────────────────
// A teardrop: one silhouette whose round head narrows to a point, drawn as a
// single path so head and tip share one continuous outline. (Drawing them as
// a circle plus a separate triangle looked detached — the head's ring cut
// across the neck and the stem read as a floating arrowhead.)
//
// Multi-band pins slice the whole teardrop into equal sectors — the shape says
// "this property scores several ways" at a glance — but the silhouette, size,
// and anchor are identical to a solid pin's, so the two never read as
// different kinds of marker. The slices are clipped to the silhouette rather
// than drawn inside the head, so the point takes its share of the colour
// instead of leaving an arc bitten across the neck.

const R = 11; // head radius
const STEM = 8; // stem length below the head's centre
const STROKE = 2;

// Artwork bounds, in user units. The tip MUST sit inside the viewBox: an
// earlier revision sized the box to `R + STROKE + STEM` tall while drawing the
// tip at `R + STEM`, which put the point past the bottom edge — the head
// rendered and the pin looked decapitated. `markerArt` derives every dimension
// and the anchor from these, so the two can't drift apart again.
const TIP_Y = R + STEM;
const MIN_X = -(R + STROKE);
const MIN_Y = -(R + STROKE);
const VIEW_W = (R + STROKE) * 2;
const VIEW_H = TIP_Y + STROKE - MIN_Y;
/** Where the tip falls down the artwork, 0..1 — the marker's anchor. */
const TIP_FRACTION = (TIP_Y - MIN_Y) / VIEW_H;

/** Radius that covers the whole silhouette — slices are clipped back to it. */
const SLICE_R = TIP_Y + STROKE;

const round = (n: number) => Number(n.toFixed(3));
const onCircle = (radians: number, radius = R): [number, number] => [
  round(radius * Math.cos(radians)),
  round(radius * Math.sin(radians)),
];

/**
 * The teardrop silhouette: the two straight flanks are the tangents from the
 * tip to the head, so the neck flows into the circle instead of meeting it at
 * a corner. Everything above the tangent points is the head's arc.
 */
function teardropPath(): string {
  // Angle, at the centre, between straight-down and each tangent point.
  const spread = Math.acos(R / TIP_Y);
  const [rx, ry] = onCircle(Math.PI / 2 - spread); // lower right
  const [lx, ly] = onCircle(Math.PI / 2 + spread); // lower left
  // Long way round (over the top), then down each flank to the tip.
  return `M ${lx} ${ly} A ${R} ${R} 0 1 1 ${rx} ${ry} L 0 ${TIP_Y} Z`;
}

/** Angle of the boundary before slice `index`, starting at 12 o'clock. */
function sliceAngle(index: number, count: number): number {
  return (index / count) * 2 * Math.PI - Math.PI / 2;
}

/**
 * One equal slice, oversized to `SLICE_R` and clipped to the silhouette by the
 * caller. Slice 0 starts at 12 o'clock and they sweep clockwise, so the best
 * band reads first.
 */
function sectorPath(index: number, count: number): string {
  if (count === 1) {
    return `M ${-SLICE_R} 0 A ${SLICE_R} ${SLICE_R} 0 1 0 ${SLICE_R} 0 A ${SLICE_R} ${SLICE_R} 0 1 0 ${-SLICE_R} 0 Z`;
  }
  const from = sliceAngle(index, count);
  const to = sliceAngle(index + 1, count);
  const [x1, y1] = onCircle(from, SLICE_R);
  const [x2, y2] = onCircle(to, SLICE_R);
  const largeArc = to - from > Math.PI ? 1 : 0;
  return `M 0 0 L ${x1} ${y1} A ${SLICE_R} ${SLICE_R} 0 ${largeArc} 1 ${x2} ${y2} Z`;
}

export interface MarkerArt {
  svg: string;
  /** Intrinsic size, in px, of the rendered artwork. */
  width: number;
  height: number;
  /** Offset of the pin tip inside the artwork — the map anchors here. */
  anchorX: number;
  anchorY: number;
}

/**
 * Build the marker SVG. `colors` are resolved CSS colors (not tokens) so this
 * stays pure: the caller reads the theme once and passes hexes in.
 */
export function markerArt(
  colors: string[],
  options: { outline: string; selected?: boolean } ,
): MarkerArt {
  const scale = options.selected ? 1.25 : 1;
  const width = VIEW_W * scale;
  const height = VIEW_H * scale;
  const drop = teardropPath();
  // Oversized slices clipped back to the silhouette: one code path for solid
  // and sliced pins, and the point is coloured by whichever slice covers it.
  const slices = colors
    .map((color, index) => `<path d="${sectorPath(index, colors.length)}" fill="${color}" />`)
    .join("");
  // Dividers are radii, not per-slice strokes — stroking each slice would
  // trace its outer arc across the neck and re-cut the shape in two.
  const dividers =
    colors.length > 1
      ? colors
          .map((_, index) => {
            const [x, y] = onCircle(sliceAngle(index, colors.length), SLICE_R);
            return `<line x1="0" y1="0" x2="${x}" y2="${y}" stroke="${options.outline}" stroke-width="${STROKE / 2}" />`;
          })
          .join("")
      : "";
  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${MIN_X} ${MIN_Y} ${VIEW_W} ${VIEW_H}">`,
    // Each marker is its own document (an <img> data URI), so a fixed id is
    // safe — ids never collide across markers on the page.
    `<clipPath id="drop"><path d="${drop}" /></clipPath>`,
    `<g clip-path="url(#drop)">${slices}${dividers}</g>`,
    `<path d="${drop}" fill="none" stroke="${options.outline}" stroke-width="${STROKE}" stroke-linejoin="round" />`,
    `</svg>`,
  ].join("");
  return {
    svg,
    width,
    height,
    anchorX: width / 2,
    // The tip, not the bottom edge — the box carries `STROKE` of padding below
    // the point so the stroked apex isn't shaved off.
    anchorY: height * TIP_FRACTION,
  };
}

export function svgDataUri(svg: string): string {
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}
