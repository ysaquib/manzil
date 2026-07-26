import { describe, expect, it } from "vitest";

import type { RubricOption } from "../src/lib/contracts";
import { deltaFill, deltaScale } from "../src/features/rubric/deltaBar";

const option = (delta: number, dealbreaker: number | null = null): RubricOption => ({
  match: { op: "eq", value: delta },
  delta,
  dealbreaker_set_score: dealbreaker,
});

describe("deltaScale", () => {
  it("is the largest magnitude on the criterion, either sign", () => {
    expect(deltaScale([option(0.5), option(0), option(-1)], 0)).toBe(1);
  });

  it("counts the unknown delta", () => {
    expect(deltaScale([option(0.25)], -0.75)).toBe(0.75);
  });

  it("ignores dealbreakers — a set score is not a delta", () => {
    // Without the filter the stored delta on a dealbreaker option would define
    // the scale and flatten every real bar on the card.
    expect(deltaScale([option(0.5), option(-9, 0)], 0)).toBe(0.5);
  });

  it("is zero when nothing on the criterion moves the score", () => {
    expect(deltaScale([option(0), option(0)], 0)).toBe(0);
    expect(deltaScale([], 0)).toBe(0);
  });
});

describe("deltaFill", () => {
  it("is the fraction of the criterion's own largest delta", () => {
    expect(deltaFill(0.25, 0.5)).toBe(0.5);
    expect(deltaFill(-0.5, 0.5)).toBe(1);
    expect(deltaFill(0, 0.5)).toBe(0);
  });

  it("clamps rather than overflowing the track", () => {
    expect(deltaFill(2, 1)).toBe(1);
  });

  it("renders nothing when the scale is zero", () => {
    expect(deltaFill(0, 0)).toBe(0);
  });
});
