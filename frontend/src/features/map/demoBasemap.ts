// Protected, release-backed basemaps for Demo sessions (DESIGN §20 v3.72).
// Geometry remains the projection contract; only the image transport changed
// from public build assets to authenticated object URLs.
import { useDemoMapAsset, useDemoRelease, type DemoMapEntry } from "../demo/api";

export interface DemoBasemap {
  url: string;
  center: { lat: number; lng: number };
  zoom: number;
  size: { width: number; height: number };
}

function useEntry(entry: DemoMapEntry | null | undefined, dark: boolean): DemoBasemap | null {
  const path = entry?.images[dark ? "dark" : "light"] ?? null;
  const url = useDemoMapAsset(path);
  if (!entry || !url) return null;
  return { url, center: entry.center, zoom: entry.zoom, size: entry.size };
}

export function usePropertyBasemap(propertyId: string, dark: boolean): DemoBasemap | null {
  const release = useDemoRelease();
  return useEntry(release.data?.map_manifest.properties?.[propertyId], dark);
}

export function useHuntBasemap(dark: boolean): DemoBasemap | null {
  const release = useDemoRelease();
  return useEntry(release.data?.map_manifest.hunt, dark);
}
