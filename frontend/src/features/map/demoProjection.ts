// Placing a coordinate on a pre-captured basemap (DM-9).
//
// The demo has no `google.maps.Map` to ask, so this reimplements the same Web
// Mercator projection `scripts/capture_demo_maps.py` used to frame the still.
// The two must agree exactly — a discrepancy does not fail loudly, it just puts
// a pin on the wrong building — so both write the formula out longhand rather
// than reaching for a library.
//
// The still is rendered `cover`, so it is scaled up until it fills the
// container and the overflow is cropped evenly. That crop is part of the
// projection: ignoring it is what makes pins drift as a window is resized.

/** Web Mercator tile size. Must match the capture script's `TILE`. */
const TILE = 256;

export interface Size {
  width: number;
  height: number;
}

export interface LatLng {
  lat: number;
  lng: number;
}

/** Longitude/latitude to unit-tile world coordinates at zoom 0. */
export function project(point: LatLng): { x: number; y: number } {
  const siny = Math.min(Math.max(Math.sin((point.lat * Math.PI) / 180), -0.9999), 0.9999);
  return {
    x: TILE * (0.5 + point.lng / 360),
    y: TILE * (0.5 - Math.log((1 + siny) / (1 - siny)) / (4 * Math.PI)),
  };
}

/**
 * Where `point` falls inside a container showing `still` with `object-fit:
 * cover`, in container pixels. Returns null when the point lands outside the
 * visible crop — the caller should not render a pin it would have to clamp,
 * because a clamped pin claims a location the map is not showing.
 */
export function projectOntoStill({
  point,
  still,
  container,
}: {
  point: LatLng;
  still: { center: LatLng; zoom: number; size: Size };
  container: Size;
}): { x: number; y: number } | null {
  if (container.width <= 0 || container.height <= 0) return null;

  const scale = Math.pow(2, still.zoom);
  const world = project(point);
  const worldCenter = project(still.center);

  // Pixel inside the still, at its captured logical size.
  const inStill = {
    x: (world.x - worldCenter.x) * scale + still.size.width / 2,
    y: (world.y - worldCenter.y) * scale + still.size.height / 2,
  };

  // `cover`: scale until both axes are filled, then centre the overflow.
  const fit = Math.max(
    container.width / still.size.width,
    container.height / still.size.height,
  );
  const rendered = { width: still.size.width * fit, height: still.size.height * fit };
  const offset = {
    x: (container.width - rendered.width) / 2,
    y: (container.height - rendered.height) / 2,
  };

  const placed = { x: offset.x + inStill.x * fit, y: offset.y + inStill.y * fit };
  if (
    placed.x < 0 ||
    placed.y < 0 ||
    placed.x > container.width ||
    placed.y > container.height
  ) {
    return null;
  }
  return placed;
}
