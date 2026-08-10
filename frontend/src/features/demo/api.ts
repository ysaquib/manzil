import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiFetch, apiFetchBlob } from "../../lib/apiClient";
import { isDemo } from "../../lib/demo";
import type { Capture } from "./replay/capture";

export interface DemoMapEntry {
  center: { lat: number; lng: number };
  zoom: number;
  size: { width: number; height: number };
  images: { light?: string; dark?: string };
}

export interface DemoMapManifest {
  scale?: number;
  tileSize?: number;
  properties?: Record<string, DemoMapEntry>;
  hunt?: DemoMapEntry | null;
}

export interface DemoRelease {
  release_id: string;
  published_at: string;
  capture_ordinals: number[];
  map_manifest: DemoMapManifest;
}

export function useDemoRelease() {
  return useQuery({
    queryKey: ["demo", "release"],
    queryFn: () => apiFetch<DemoRelease>("/v1/demo/release"),
    enabled: isDemo(),
    staleTime: Infinity,
    // This is also the revocation sentinel mounted by DemoBanner. Direct
    // PostgREST reads become empty when the kill switch flips, so one bounded
    // protected API check is what turns an already-open page into an honest
    // session-ended redirect instead of leaving cached Hunt data on screen.
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useDemoCapture(ordinal: number | null) {
  return useQuery({
    queryKey: ["demo", "capture", ordinal],
    queryFn: () => apiFetch<Capture>(`/v1/demo/release/captures/${ordinal}`),
    enabled: isDemo() && ordinal !== null,
    staleTime: Infinity,
    retry: false,
  });
}

/** Load a protected map as a short-lived in-tab object URL. */
export function useDemoMapAsset(path: string | null): string | null {
  const query = useQuery({
    queryKey: ["demo", "map", path],
    queryFn: ({ signal }) => apiFetchBlob(`/v1/demo/release/maps/${path}`, signal),
    enabled: isDemo() && path !== null,
    staleTime: Infinity,
    retry: false,
  });
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(query.data);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [query.data]);

  return url;
}
