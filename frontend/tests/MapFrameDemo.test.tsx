// DM-9's acceptance criterion for the map surfaces: a demo session renders a
// pre-captured basemap and never reaches for the Maps JS API.
//
// `maps.googleapis.com` must not appear in the network panel — asserting that
// `loadGoogleMaps` was never called is the testable form of that claim.
import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const isDemo = vi.fn(() => true);
// Enough of the Maps namespace for the non-demo path to construct a map; the
// point of that case is only that it *tried*.
const mapsStub = {
  Map: class {
    setOptions() {}
  },
} as never;
const loadGoogleMaps = vi.fn(() => Promise.resolve(mapsStub));
const mapsConfigured = vi.fn(() => true);

vi.mock("../src/lib/demo", () => ({ isDemo: () => isDemo() }));
vi.mock("../src/lib/googleMaps", () => ({
  loadGoogleMaps: () => loadGoogleMaps(),
  mapsConfigured: () => mapsConfigured(),
  googleMapsLink: () => "https://maps.google.com/",
}));

const BASEMAP = {
  url: "/assets/perennial-corktown-light.webp",
  center: { lat: 42.3308889, lng: -83.0690978 },
  zoom: 15,
  size: { width: 640, height: 260 },
};

function renderFrame(node: React.ReactElement) {
  return render(<MantineProvider>{node}</MantineProvider>);
}

describe("MapFrame in a demo session", () => {
  beforeEach(() => {
    isDemo.mockReturnValue(true);
    loadGoogleMaps.mockClear();
  });

  it("renders the still and never loads the Maps JS API", async () => {
    const { MapFrame } = await import("../src/features/map/MapFrame");
    renderFrame(<MapFrame height={200} onReady={() => {}} demoBasemap={BASEMAP} />);

    const still = screen.getByRole("img", { name: /pre-captured map/i });
    expect(still).toHaveStyle({ backgroundImage: `url(${BASEMAP.url})` });
    expect(loadGoogleMaps).not.toHaveBeenCalled();
  });

  it("says so plainly when no still was captured, rather than loading the real map", async () => {
    const { MapFrame } = await import("../src/features/map/MapFrame");
    renderFrame(<MapFrame height={200} onReady={() => {}} demoBasemap={null} />);

    expect(screen.getByText("Map not shown")).toBeInTheDocument();
    expect(loadGoogleMaps).not.toHaveBeenCalled();
  });

  it("loads the real map when the session is not a demo", async () => {
    isDemo.mockReturnValue(false);
    const { MapFrame } = await import("../src/features/map/MapFrame");
    renderFrame(<MapFrame height={200} onReady={() => {}} demoBasemap={BASEMAP} />);

    expect(loadGoogleMaps).toHaveBeenCalled();
    expect(screen.queryByRole("img", { name: /pre-captured map/i })).not.toBeInTheDocument();
  });
});
