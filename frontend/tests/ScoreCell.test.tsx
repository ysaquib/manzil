import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatScore, ScoreCell, scoreColor } from "../src/features/listings/ScoreCell";
import { renderWithProviders } from "./testUtils";

describe("scoreColor", () => {
  // Default max is the §9.3 engine clamp (15); green anchors on the base (10).
  it("maps engine-domain bands to colors", () => {
    expect(scoreColor(10)).toBe("scoreHighest");
    expect(scoreColor(12.5)).toBe("scoreHighest");
    expect(scoreColor(8)).toBe("scoreHigh");
    expect(scoreColor(7.5)).toBe("scoreGood");
    expect(scoreColor(5)).toBe("scoreMid");
    expect(scoreColor(4)).toBe("scoreMid");
    expect(scoreColor(0)).toBe("scorePoor");
  });

  it("respects a custom base", () => {
    expect(scoreColor(9, 10)).toBe("scoreHigh");
    expect(scoreColor(1, 10)).toBe("scorePoor");
  });

  it("does not divide by zero", () => {
    expect(scoreColor(0, 0)).toBe("scorePoorest");
  });
});

describe("formatScore", () => {
  it("keeps half points visible", () => {
    expect(formatScore(9.5)).toBe("9.5");
    expect(formatScore(10)).toBe("10");
  });
});

describe("ScoreCell selection state", () => {
  it("marks an ephemeral filter-selected Floor Plan", () => {
    renderWithProviders(
      <ScoreCell
        total={8}
        filterSelected
        planName="Lower-score early"
        planCount={2}
      />,
    );

    expect(screen.getByLabelText("filter-selected Floor Plan")).toBeInTheDocument();
  });
});
