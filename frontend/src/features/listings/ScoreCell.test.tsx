import { describe, expect, it } from "vitest";

import { formatScore, scoreColor } from "./ScoreCell";

describe("scoreColor", () => {
  // Default max is the §9.3 engine clamp (15); green anchors on the base (10).
  it("maps engine-domain bands to colors", () => {
    expect(scoreColor(10)).toBe("green");
    expect(scoreColor(12.5)).toBe("green");
    expect(scoreColor(8)).toBe("lime");
    expect(scoreColor(7.5)).toBe("lime");
    expect(scoreColor(5)).toBe("yellow");
    expect(scoreColor(4)).toBe("red");
    expect(scoreColor(0)).toBe("red");
  });

  it("respects a custom max", () => {
    expect(scoreColor(9, 10)).toBe("green");
    expect(scoreColor(1, 10)).toBe("red");
  });

  it("does not divide by zero", () => {
    expect(scoreColor(0, 0)).toBe("red");
  });
});

describe("formatScore", () => {
  it("keeps half points visible", () => {
    expect(formatScore(9.5)).toBe("9.5");
    expect(formatScore(10)).toBe("10");
  });
});
