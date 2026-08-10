// The demo basemap projection (DM-9). These assertions matter because a wrong
// projection does not throw — it just puts a pin on the wrong building.
import { describe, expect, it } from "vitest";

import { project, projectOntoStill } from "../src/features/map/demoProjection";

const STILL = {
  center: { lat: 42.3308889, lng: -83.0690978 },
  zoom: 15,
  size: { width: 640, height: 260 },
};

describe("project", () => {
  it("puts the null island at the centre of the zoom-0 tile", () => {
    const origin = project({ lat: 0, lng: 0 });
    expect(origin.x).toBeCloseTo(128, 6);
    expect(origin.y).toBeCloseTo(128, 6);
  });

  it("is monotonic: east increases x, north decreases y", () => {
    expect(project({ lat: 0, lng: 10 }).x).toBeGreaterThan(project({ lat: 0, lng: -10 }).x);
    expect(project({ lat: 40, lng: 0 }).y).toBeLessThan(project({ lat: 10, lng: 0 }).y);
  });

  it("clamps near the poles instead of diverging", () => {
    expect(Number.isFinite(project({ lat: 90, lng: 0 }).y)).toBe(true);
    expect(Number.isFinite(project({ lat: -90, lng: 0 }).y)).toBe(true);
  });
});

describe("projectOntoStill", () => {
  it("places the still's own centre at the container's centre", () => {
    const at = projectOntoStill({
      point: STILL.center,
      still: STILL,
      container: { width: 640, height: 260 },
    });
    expect(at).not.toBeNull();
    expect(at!.x).toBeCloseTo(320, 6);
    expect(at!.y).toBeCloseTo(130, 6);
  });

  it("keeps the centre centred when the container crops the still", () => {
    // A container of a different aspect ratio: `cover` scales up and crops
    // evenly, so the centre must not move.
    const at = projectOntoStill({
      point: STILL.center,
      still: STILL,
      container: { width: 300, height: 400 },
    });
    expect(at!.x).toBeCloseTo(150, 6);
    expect(at!.y).toBeCloseTo(200, 6);
  });

  it("puts a point east of centre to the right, and north above", () => {
    const at = projectOntoStill({
      point: { lat: STILL.center.lat + 0.002, lng: STILL.center.lng + 0.002 },
      still: STILL,
      container: { width: 640, height: 260 },
    })!;
    expect(at.x).toBeGreaterThan(320);
    expect(at.y).toBeLessThan(130);
  });

  it("returns null rather than clamping a point outside the crop", () => {
    // Same zoom, a coordinate hundreds of miles away: off the still entirely.
    expect(
      projectOntoStill({
        point: { lat: 47.61, lng: -122.32 },
        still: STILL,
        container: { width: 640, height: 260 },
      }),
    ).toBeNull();
  });

  it("returns null for a container that has not been measured yet", () => {
    expect(
      projectOntoStill({ point: STILL.center, still: STILL, container: { width: 0, height: 0 } }),
    ).toBeNull();
  });

  it("agrees with the capture script's zoom-3 hunt-wide framing", () => {
    // The manifest's hunt still: every demo Property must land inside it, or
    // the map page would silently drop pins.
    const hunt = {
      center: { lat: 40.2078, lng: -96.6909 },
      zoom: 3,
      size: { width: 640, height: 400 },
    };
    const container = { width: 900, height: 600 };
    for (const point of [
      { lat: 47.6130524, lng: -122.3197543 }, // Seattle
      { lat: 42.3239138, lng: -71.0620184 }, // Boston
      { lat: 32.8026144, lng: -96.7967404 }, // Dallas
    ]) {
      expect(projectOntoStill({ point, still: hunt, container })).not.toBeNull();
    }
  });
});
