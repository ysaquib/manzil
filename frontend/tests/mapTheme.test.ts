import { describe, expect, it } from "vitest";

import { markerOutline, scoreHex } from "../src/features/map/mapTheme";

// jsdom defines none of the Mantine custom properties, so these exercise the
// fallback branch — which is exactly the contract worth pinning: the values
// baked into the source, not whatever a stylesheet happens to supply.
describe("markerOutline", () => {
  it("is black in light mode and white in dark mode", () => {
    expect(markerOutline(false)).toBe("#000000");
    expect(markerOutline(true)).toBe("#FFFEFB");
  });

  // The outline contrasts with the *basemap* — pale in light, charcoal in
  // dark — so it must invert with the scheme rather than track the page body.
  it("inverts with the color scheme", () => {
    expect(markerOutline(true)).not.toBe(markerOutline(false));
  });
});

describe("scoreHex", () => {
  it("reads a lighter shade in dark mode than in light", () => {
    expect(scoreHex("scoreHighest", true)).not.toBe(scoreHex("scoreHighest", false));
  });
});
