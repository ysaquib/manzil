// The Overview's Visit column (VC-8).
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { VisitUnitGroupScore } from "../src/features/visits/types";
import {
  VisitScoreCell,
  formatVisitScore,
  visitScoreTone,
  visitScoreTooltip,
} from "../src/features/visits/VisitScoreCell";
import { renderWithProviders } from "./testUtils";

function entry(partial: Partial<VisitUnitGroupScore> = {}): VisitUnitGroupScore {
  return {
    hunt_listing_id: "hl1",
    unit_group_key: "2-2",
    score: 4.2,
    best_visit_unit_id: "un1",
    best_visit_id: "v1",
    best_visited_at: new Date(Date.now() - 86_400_000).toISOString(),
    rater_count: 2,
    unit_count: 1,
    ...partial,
  };
}

describe("formatVisitScore", () => {
  it("always shows one decimal, so a column of scores lines up", () => {
    expect(formatVisitScore(4)).toBe("4.0");
    expect(formatVisitScore(2.25)).toBe("2.3");
  });
});

describe("visitScoreTone", () => {
  it("reads warm at the top and cool at the bottom", () => {
    expect(visitScoreTone(4.5)).toBe("sage");
    expect(visitScoreTone(3.2)).toBe("olive");
    expect(visitScoreTone(2.1)).toBe("ochre");
    expect(visitScoreTone(1.4)).toBe("brick");
  });
});

describe("visitScoreTooltip", () => {
  it("says the number is a tour score and not part of Fit", () => {
    // The one thing a reader must not conclude is that this was folded into
    // the rubric score.
    expect(visitScoreTooltip(entry())).toMatch(/never part of Fit/);
  });

  it("explains a best-of when more than one door was toured", () => {
    expect(visitScoreTooltip(entry({ unit_count: 3 }))).toMatch(/Best of 3 units toured/);
  });

  it("says nothing about best-of for a single door", () => {
    expect(visitScoreTooltip(entry())).not.toMatch(/Best of/);
  });

  it("counts the raters, singular and plural", () => {
    expect(visitScoreTooltip(entry({ rater_count: 1 }))).toMatch(/1 member rated it/);
    expect(visitScoreTooltip(entry({ rater_count: 3 }))).toMatch(/3 members rated it/);
  });
});

describe("VisitScoreCell", () => {
  it("shows an em dash for a Unit Group nobody toured, never a zero", () => {
    // A zero would read as a terrible review rather than an absence.
    renderWithProviders(<VisitScoreCell entry={undefined} />);
    expect(screen.getByLabelText("not visited")).toHaveTextContent("—");
  });

  it("shows the score", () => {
    renderWithProviders(<VisitScoreCell entry={entry()} />);
    expect(screen.getByText("4.2")).toBeInTheDocument();
  });

  it("marks a best-of with the ×N affordance the score cell already uses", () => {
    renderWithProviders(<VisitScoreCell entry={entry({ unit_count: 3 })} />);
    expect(screen.getByText("×3")).toBeInTheDocument();
  });

  it("does not clutter a single-unit row with ×1", () => {
    renderWithProviders(<VisitScoreCell entry={entry()} />);
    expect(screen.queryByText("×1")).not.toBeInTheDocument();
  });
});
