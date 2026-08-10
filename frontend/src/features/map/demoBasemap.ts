// Pre-captured basemaps for demo sessions (DM-9, DESIGN §16).
//
// `MapFrame` never calls `loadGoogleMaps()` when `isDemo()`, so these stills are
// what a visitor sees instead. They are basemaps only: the app draws real pins
// over them from live data, which keeps pin colours honest when the Rubric
// changes and keeps them clickable. `scripts/capture_demo_maps.py` produces
// both the images and `manifest.json`.
//
// The manifest's `center`/`zoom`/`size` are a contract, not documentation:
// `demoProjection.ts` needs them to place a coordinate on the still, and a
// still whose metadata drifts puts every pin in the wrong place.
import manifest from "../demo/maps/manifest.json";

/** Vite resolves these to fingerprinted, lazily-fetched asset URLs. */
const assets = import.meta.glob<string>("../demo/maps/*.webp", {
  eager: true,
  query: "?url",
  import: "default",
});

function assetUrl(fileName: string): string | null {
  return assets[`../demo/maps/${fileName}`] ?? null;
}

export interface DemoBasemap {
  url: string;
  center: { lat: number; lng: number };
  zoom: number;
  /** Logical size the still was captured at, before `scale`. */
  size: { width: number; height: number };
}

interface ManifestEntry {
  center: { lat: number; lng: number };
  zoom: number;
  size: { width: number; height: number };
  images: Record<string, string>;
}

function resolve(entry: ManifestEntry | undefined, dark: boolean): DemoBasemap | null {
  if (!entry) return null;
  const url = assetUrl(entry.images[dark ? "dark" : "light"] ?? "");
  if (!url) return null;
  return { url, center: entry.center, zoom: entry.zoom, size: entry.size };
}

/**
 * Slug a Property name the same way the capture script does. Matching on name
 * rather than id is deliberate: the demo database is reseeded and re-ingested,
 * which mints new Listing ids, but the Property names are the stable thing a
 * capture is actually *of*.
 */
export function basemapSlug(propertyName: string): string {
  return propertyName.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

const properties = manifest.properties as unknown as Record<string, ManifestEntry>;

/** The still for one Property's drawer map, or null when none was captured. */
export function propertyBasemap(propertyName: string, dark: boolean): DemoBasemap | null {
  return resolve(properties[basemapSlug(propertyName)], dark);
}

/** The hunt-wide still behind the map page. */
export function huntBasemap(dark: boolean): DemoBasemap | null {
  return resolve(manifest.hunt as unknown as ManifestEntry, dark);
}
