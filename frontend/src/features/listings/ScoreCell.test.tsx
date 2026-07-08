import { describe, expect, it } from "vitest";

import { scoreColor } from "./ScoreCell";

describe("scoreColor", () => {
  it("maps proportional bands to colors", () => {
    expect(scoreColor(90)).toBe("green");
    expect(scoreColor(60)).toBe("lime");
    expect(scoreColor(30)).toBe("yellow");
    expect(scoreColor(10)).toBe("red");
  });

  it("respects a custom max", () => {
    expect(scoreColor(9, 10)).toBe("green");
    expect(scoreColor(1, 10)).toBe("red");
  });

  it("does not divide by zero", () => {
    expect(scoreColor(0, 0)).toBe("red");
  });
});
