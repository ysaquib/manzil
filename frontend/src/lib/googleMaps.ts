// Google Maps JavaScript API loader (DESIGN §7 vendor, §13.1 map surfaces).
//
// One <script> per document, promise-cached so every map on the page shares a
// single load. The browser key is a SEPARATE, HTTP-referrer-restricted key
// from the worker's server-side Maps key (IMPLEMENTATION §1) — a VITE_* value
// ships to every visitor, so the worker key must never be reused here.
//
// Deliberately no `mapId`: without one the classic `styles` array works, which
// is how the dark scheme is themed (a cloud Map ID would move styling out of
// the repo and add another external gate). That also keeps `google.maps.Marker`
// available, whose data-URI SVG icons carry the score colors.

export const MAPS_API_KEY: string =
  (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined) ?? "";

export function mapsConfigured(): boolean {
  return MAPS_API_KEY.trim() !== "";
}

const SCRIPT_ID = "manzil-google-maps";

// What the map surfaces actually construct: `maps` for Map, `marker` for
// Marker, `core` for LatLngBounds/Size/Point/event. Libraries also register
// themselves on the global `google.maps` namespace, so call sites keep using
// `new google.maps.Marker(...)` once these have resolved.
const LIBRARIES = ["maps", "marker", "core"] as const;

let loading: Promise<typeof google.maps> | null = null;

export function loadGoogleMaps(): Promise<typeof google.maps> {
  if (loading) return loading;
  if (!mapsConfigured()) {
    return Promise.reject(new Error("VITE_GOOGLE_MAPS_API_KEY is not set"));
  }

  loading = injectBootstrap()
    .then(async () => {
      // The script's load event is NOT the ready signal. Under `loading=async`
      // the bootstrap deliberately suppresses execution on that event and
      // installs only `importLibrary`; every constructor arrives with its
      // library. Resolving on `load` handed callers a `google.maps` whose
      // `Map` was still undefined — the map hung on its loader forever.
      await Promise.all(LIBRARIES.map((library) => google.maps.importLibrary(library)));
      return google.maps;
    })
    .catch((error: unknown) => {
      // Let a later mount retry — a transient network failure should not
      // permanently poison the cached promise.
      loading = null;
      document.getElementById(SCRIPT_ID)?.remove();
      throw error;
    });

  return loading;
}

function importLibraryReady(): boolean {
  return typeof window !== "undefined" && typeof window.google?.maps?.importLibrary === "function";
}

/** Poll until the async bootstrap exposes `importLibrary` (or time out). */
function waitForImportLibrary(timeoutMs = 15_000): Promise<void> {
  if (importLibraryReady()) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (importLibraryReady()) {
        resolve();
        return;
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error("Google Maps bootstrap timed out"));
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
}

/** Resolves once the bootstrap script has run and `importLibrary` exists. */
function injectBootstrap(): Promise<void> {
  if (importLibraryReady()) return Promise.resolve();

  return new Promise((resolve, reject) => {
    const ready = () => {
      waitForImportLibrary().then(resolve, reject);
    };

    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      // Tag already in the document — load may have finished before we
      // subscribed (cache hit, Strict Mode remount). Poll instead of waiting
      // for a `load` event that will never fire again.
      existing.addEventListener("error", () => reject(new Error("Google Maps failed to load")), {
        once: true,
      });
      ready();
      return;
    }

    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.async = true;
    const params = new URLSearchParams({
      key: MAPS_API_KEY,
      v: "weekly",
      loading: "async",
    });
    script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
    script.addEventListener("load", () => ready(), { once: true });
    script.addEventListener("error", () => reject(new Error("Google Maps failed to load")), {
      once: true,
    });
    document.head.appendChild(script);
  });
}

/** Deep-link to Google Maps for a property, by coordinates when we have them. */
export function googleMapsLink(
  address: string,
  lat: number | null,
  lng: number | null,
): string {
  const query = lat !== null && lng !== null ? `${lat},${lng}` : address;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}
