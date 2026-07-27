import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The loader caches its promise in module scope, so each test re-imports a
// fresh copy. `import.meta.env` is stubbed before the import because the key
// is read at module-evaluation time.
async function freshLoader(key = "test-key") {
  vi.resetModules();
  vi.stubEnv("VITE_GOOGLE_MAPS_API_KEY", key);
  return import("../src/lib/googleMaps");
}

/** The <script> the loader appended, once it has been added to the head. */
function bootstrapScript(): HTMLScriptElement | null {
  return document.getElementById("manzil-google-maps") as HTMLScriptElement | null;
}

/**
 * Stand in for the Maps bootstrap: firing `load` installs ONLY `importLibrary`,
 * exactly as `loading=async` does — no `Map` constructor yet.
 */
function fireBootstrapLoad(importLibrary: (name: string) => Promise<unknown>) {
  (window as unknown as { google: unknown }).google = { maps: { importLibrary } };
  bootstrapScript()?.dispatchEvent(new Event("load"));
}

beforeEach(() => {
  bootstrapScript()?.remove();
  Reflect.deleteProperty(window as unknown as Record<string, unknown>, "google");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("mapsConfigured", () => {
  it("is false with no key, so surfaces can degrade instead of erroring", async () => {
    const { mapsConfigured } = await freshLoader("");
    expect(mapsConfigured()).toBe(false);
  });

  it("is true once a key is present", async () => {
    const { mapsConfigured } = await freshLoader();
    expect(mapsConfigured()).toBe(true);
  });
});

describe("loadGoogleMaps", () => {
  it("rejects without a key rather than injecting an unusable script", async () => {
    const { loadGoogleMaps } = await freshLoader("");
    await expect(loadGoogleMaps()).rejects.toThrow(/VITE_GOOGLE_MAPS_API_KEY/);
    expect(bootstrapScript()).toBeNull();
  });

  it("requests the bootstrap with loading=async and the configured key", async () => {
    const { loadGoogleMaps } = await freshLoader("abc123");
    void loadGoogleMaps();
    const src = new URL(bootstrapScript()!.src);
    expect(src.origin + src.pathname).toBe("https://maps.googleapis.com/maps/api/js");
    expect(src.searchParams.get("key")).toBe("abc123");
    expect(src.searchParams.get("loading")).toBe("async");
  });

  // THE regression. Under `loading=async` the script's load event fires while
  // `google.maps` holds only `importLibrary`; resolving there handed callers a
  // namespace whose `Map` was undefined, and the surface hung on its loader.
  it("waits for importLibrary, not the script's load event", async () => {
    const { loadGoogleMaps } = await freshLoader();
    let releaseLibraries: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      releaseLibraries = resolve;
    });
    const importLibrary = vi.fn(async (name: string) => {
      await gate;
      // Libraries register themselves on the global namespace as they land.
      const maps = (window as unknown as { google: { maps: Record<string, unknown> } }).google
        .maps;
      if (name === "maps") maps.Map = class {};
      if (name === "marker") maps.Marker = class {};
      return {};
    });

    let settled = false;
    const promise = loadGoogleMaps().then((maps) => {
      settled = true;
      return maps;
    });

    fireBootstrapLoad(importLibrary);
    // Drain the microtask queue: a promise chain needs several ticks, so a
    // single `await Promise.resolve()` would report "not settled" either way.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(settled).toBe(false); // load fired — still not ready

    releaseLibraries();
    const maps = await promise;
    expect(settled).toBe(true);
    // The whole point: what callers receive can actually construct a Map.
    expect(maps.Map).toBeTypeOf("function");
  });

  it("polls after the load event until importLibrary exists", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const importLibrary = vi.fn(async (name: string) => {
      const maps = (window as unknown as { google: { maps: Record<string, unknown> } }).google
        .maps;
      if (name === "maps") maps.Map = class {};
      if (name === "marker") maps.Marker = class {};
      return {};
    });

    let settled = false;
    const promise = loadGoogleMaps().then((maps) => {
      settled = true;
      return maps;
    });

    // Simulate the load event winning the race over bootstrap execution.
    bootstrapScript()?.dispatchEvent(new Event("load"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(settled).toBe(false);

    (window as unknown as { google: unknown }).google = { maps: { importLibrary } };
    const maps = await promise;
    expect(settled).toBe(true);
    expect(maps.Map).toBeTypeOf("function");
  });

  it("does not hang when the script tag already exists and load already fired", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const importLibrary = vi.fn(async (name: string) => {
      const maps = (window as unknown as { google: { maps: Record<string, unknown> } }).google
        .maps;
      if (name === "maps") maps.Map = class {};
      if (name === "marker") maps.Marker = class {};
      return {};
    });

    const script = document.createElement("script");
    script.id = "manzil-google-maps";
    document.head.appendChild(script);
    (window as unknown as { google: unknown }).google = { maps: { importLibrary } };

    const maps = await loadGoogleMaps();
    expect(maps.Map).toBeTypeOf("function");
  });

  it("imports every library the map surfaces construct from", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const importLibrary = vi.fn(async () => ({}));
    const promise = loadGoogleMaps();
    fireBootstrapLoad(importLibrary);
    await promise;
    expect(importLibrary.mock.calls.flat().sort()).toEqual(["core", "maps", "marker"]);
  });

  it("caches one script and one promise across concurrent callers", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const importLibrary = vi.fn(async () => ({}));
    const first = loadGoogleMaps();
    const second = loadGoogleMaps();
    expect(first).toBe(second);
    fireBootstrapLoad(importLibrary);
    await first;
    expect(document.querySelectorAll("#manzil-google-maps")).toHaveLength(1);
  });

  // A dead network on the first visit must not brick the surface for the rest
  // of the session — the next mount gets to try again from scratch.
  it("clears the cached promise and script so a later mount can retry", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const failing = loadGoogleMaps();
    bootstrapScript()!.dispatchEvent(new Event("error"));
    await expect(failing).rejects.toThrow(/failed to load/);
    expect(bootstrapScript()).toBeNull();

    const retry = loadGoogleMaps();
    expect(retry).not.toBe(failing);
    expect(bootstrapScript()).not.toBeNull();
    fireBootstrapLoad(vi.fn(async () => ({})));
    await expect(retry).resolves.toBeDefined();
  });
});

describe("googleMapsLink", () => {
  it("prefers coordinates over the address when the property is geocoded", async () => {
    const { googleMapsLink } = await freshLoader();
    expect(googleMapsLink("1 Main St", 42.3, -83.1)).toContain("query=42.3%2C-83.1");
  });

  it("falls back to the address when there is no geocode", async () => {
    const { googleMapsLink } = await freshLoader();
    expect(googleMapsLink("1 Main St", null, null)).toContain("query=1%20Main%20St");
  });
});
