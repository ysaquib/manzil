import { describe, expect, it } from "vitest";

import { formatScore, scoreBand, scoreColor, scoreLabel } from "../src/features/listings/scoreBands";

describe("scoreBand / scoreColor / scoreLabel", () => {
  it("maps totals to bands on inclusive-lower thresholds (base 10)", () => {
    expect(scoreBand(12.5)).toBe(0);
    expect(scoreBand(10)).toBe(0); // exactly base = highest
    expect(scoreBand(9.5)).toBe(1);
    expect(scoreBand(8)).toBe(1);
    expect(scoreBand(6)).toBe(2);
    expect(scoreBand(4)).toBe(3);
    expect(scoreBand(2)).toBe(4);
    expect(scoreBand(0)).toBe(5);
  });
  it("labels match the bands", () => {
    expect(scoreLabel(12.5)).toBe("Exceptional Match");
    expect(scoreLabel(10)).toBe("Exceptional Match");
    expect(scoreLabel(9)).toBe("Strong Match");
    expect(scoreLabel(7)).toBe("Acceptable Match");
    expect(scoreLabel(5)).toBe("Weak Match");
    expect(scoreLabel(3)).toBe("Poor Match");
    expect(scoreLabel(1)).toBe("Unacceptable");
  });
  it("colors stay consistent with the pre-existing scoreColor bands", () => {
    expect(scoreColor(10)).toBe("scoreHighest");
    expect(scoreColor(8)).toBe("scoreHigh");
    expect(scoreColor(6)).toBe("scoreGood");
    expect(scoreColor(4)).toBe("scoreMid");
    expect(scoreColor(2)).toBe("scoreLow");
    expect(scoreColor(0)).toBe("scorePoor");
  });
  it("preserves the original base=0 edge (0/0 = NaN falls through to poorest)", () => {
    expect(scoreBand(0, 0)).toBe(6);
    expect(scoreColor(0, 0)).toBe("scorePoorest");
  });
  it("formats half-points, keeps integers clean", () => {
    expect(formatScore(9.5)).toBe("9.5");
    expect(formatScore(10)).toBe("10");
  });
});
