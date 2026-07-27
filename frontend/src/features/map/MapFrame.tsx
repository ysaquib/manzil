// Shared map shell: loads the Maps JS API once, builds one `google.maps.Map`
// into a container, and owns every non-map state the surface can be in
// (no key configured, loading, failed). Both map surfaces (§13.2) render
// through it so their empty and error states stay identical.
import { Alert, Box, Center, Loader, Stack, Text, useComputedColorScheme } from "@mantine/core";
import { IconMapOff } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { loadGoogleMaps, mapsConfigured } from "../../lib/googleMaps";
import { BASE_MAP_OPTIONS, basemapStyle } from "./mapTheme";

type Status = "unconfigured" | "loading" | "ready" | "error";

export function MapFrame({
  height,
  options,
  onReady,
  radius = "md",
  emptyLabel,
}: {
  /** CSS height — a number is px, a string passes through (e.g. "100%"). */
  height: number | string;
  /** Initial map options, merged over the shared chrome defaults. */
  options?: google.maps.MapOptions;
  /** Called once the map exists, and again whenever the color scheme flips. */
  onReady: (map: google.maps.Map) => void;
  radius?: string;
  /** Shown over the map when there is nothing to plot. */
  emptyLabel?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const [status, setStatus] = useState<Status>(
    mapsConfigured() ? "loading" : "unconfigured",
  );
  const scheme = useComputedColorScheme("light");

  useEffect(() => {
    if (!mapsConfigured()) return;
    let cancelled = false;
    void loadGoogleMaps().then(
      (maps) => {
        if (cancelled || !containerRef.current) return;
        if (!mapRef.current) {
          mapRef.current = new maps.Map(containerRef.current, {
            // Neutral pre-fit frame; both callers immediately center or
            // fitBounds, so this is only what shows for one paint.
            center: { lat: 39.5, lng: -98.35 },
            zoom: 3,
            ...BASE_MAP_OPTIONS,
            styles: basemapStyle(scheme === "dark"),
            ...options,
          });
        }
        setStatus("ready");
        onReadyRef.current(mapRef.current);
      },
      () => {
        if (!cancelled) setStatus("error");
      },
    );
    return () => {
      cancelled = true;
    };
    // Deliberately empty: `options` and `scheme` are initial-render concerns
    // here (a new object identity each parent render would rebuild the map).
    // Scheme changes are handled by the restyle effect below.
  }, []);

  // Re-style (not rebuild) when the color scheme flips, then let the owner
  // repaint its markers against the new palette.
  useEffect(() => {
    if (status !== "ready" || !mapRef.current) return;
    mapRef.current.setOptions({ styles: basemapStyle(scheme === "dark") });
    onReadyRef.current(mapRef.current);
  }, [scheme, status]);

  return (
    <Box
      pos="relative"
      h={height}
      style={{
        borderRadius: `var(--mantine-radius-${radius})`,
        overflow: "hidden",
        border: "1px solid var(--mantine-color-default-border)",
        backgroundColor: "var(--mantine-color-default-hover)",
      }}
    >
      <Box ref={containerRef} h="100%" w="100%" />

      {status === "loading" && (
        <Center pos="absolute" inset={0}>
          <Loader size="sm" />
        </Center>
      )}

      {status === "unconfigured" && (
        <Center pos="absolute" inset={0} p="md">
          <Alert color="gray" icon={<IconMapOff size={18} stroke={1.5} />} title="Map unavailable">
            <Text size="sm">
              Set <Text span ff="monospace" fz="xs">VITE_GOOGLE_MAPS_API_KEY</Text> in{" "}
              <Text span ff="monospace" fz="xs">frontend/.env.local</Text> to show maps. Use a
              browser key restricted by HTTP referrer — not the worker&apos;s server key.
            </Text>
          </Alert>
        </Center>
      )}

      {status === "error" && (
        <Center pos="absolute" inset={0} p="md">
          <Alert color="red" title="Couldn&apos;t load the map">
            <Text size="sm">
              Google Maps didn&apos;t load. Check the browser key&apos;s referrer restrictions and
              that the Maps JavaScript API is enabled for the project.
            </Text>
          </Alert>
        </Center>
      )}

      {status === "ready" && emptyLabel && (
        <Center
          pos="absolute"
          inset={0}
          style={{ backgroundColor: "var(--mantine-color-body)", opacity: 0.88 }}
        >
          <Stack align="center" gap={6}>
            <IconMapOff size={26} stroke={1.5} color="var(--mantine-color-dimmed)" />
            <Text size="sm" c="dimmed" ta="center" maw={320}>
              {emptyLabel}
            </Text>
          </Stack>
        </Center>
      )}
    </Box>
  );
}
