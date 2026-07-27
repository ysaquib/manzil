// Map theming (frontend/AGENTS.md "dark mode via Mantine only"): marker colors
// and basemap styling are read from the theme's CSS custom properties at paint
// time rather than hard-coded, so "Dusk & clay" stays the single source of
// colour truth and both schemes track `theme.ts` automatically.
//
// A raster/vector basemap cannot consume CSS variables, so the classic
// `styles` array below is the one place map chrome is expressed as literals —
// each entry is a de-saturated neutral chosen to sit under the score palette
// without competing with it (deliberately no cloud Map ID: see lib/googleMaps).

/** Resolve a CSS custom property against the document, with a fallback. */
export function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Hex for a `scoreColor()` token. Light mode leans one shade darker so the
 * marker holds its own against a pale basemap; dark mode leans lighter.
 */
export function scoreHex(token: string, dark: boolean): string {
  return cssVar(`--mantine-color-${token}-${dark ? 4 : 6}`, dark ? "#AEA69F" : "#756D66");
}

/**
 * Marker outline and slice dividers: black in light mode, white in dark.
 *
 * Deliberately the inverse of the page body it used to track — the pin should
 * contrast with the *basemap*, which is pale in light mode and charcoal in
 * dark, not blend into the surrounding chrome. Both come from `theme.ts`
 * (`white` is the palette's warm off-white), so this stays token-driven.
 */
export function markerOutline(dark: boolean): string {
  return dark
    ? cssVar("--mantine-color-white", "#FFFEFB")
    : cssVar("--mantine-color-black", "#000000");
}

// Dark basemap: muted charcoal land, dimmed labels, no points of interest
// competing with our own pins. Light mode keeps Google's default styling and
// only drops business POIs for the same reason.
const DARK_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#262320" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#8B867E" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#161412" }] },
  { featureType: "administrative", elementType: "geometry", stylers: [{ color: "#48443E" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "park", elementType: "geometry", stylers: [{ color: "#302C27" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#3D3933" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#8B867E" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#48443E" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#201D1A" }] },
];

const LIGHT_STYLE: google.maps.MapTypeStyle[] = [
  { featureType: "poi.business", stylers: [{ visibility: "off" }] },
  { featureType: "transit", elementType: "labels.icon", stylers: [{ visibility: "off" }] },
];

export function basemapStyle(dark: boolean): google.maps.MapTypeStyle[] {
  return dark ? DARK_STYLE : LIGHT_STYLE;
}

/** Chrome we never want on an embedded map: Street View pegman, map-type flips. */
export const BASE_MAP_OPTIONS: google.maps.MapOptions = {
  mapTypeControl: false,
  streetViewControl: false,
  fullscreenControl: false,
  clickableIcons: false,
};
