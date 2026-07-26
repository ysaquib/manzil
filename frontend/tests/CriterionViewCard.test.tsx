import { MantineProvider } from "@mantine/core";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CatalogEntry, RubricCriterion } from "../src/features/rubric/api";
import { CriterionViewCard } from "../src/features/rubric/CriterionViewCard";

const entry: CatalogEntry = {
  key: "beds",
  label: "Number of bedrooms",
  category: "unit",
  domain: "rent",
  fact_scope: "floor_plan",
  value_schema: { type: "number" },
  default_options: [],
  extraction_hint: "",
  requires_tool: null,
  refresh_class: "static",
};

const criterion = (overrides: Partial<RubricCriterion> = {}): RubricCriterion => ({
  catalog_key: "beds",
  custom_def: null,
  enabled: true,
  options: [
    { match: { op: "eq", value: 2 }, delta: 0.5, dealbreaker_set_score: null },
    { match: { op: "eq", value: 1 }, delta: 0, dealbreaker_set_score: null },
    { match: { op: "eq", value: 0 }, delta: -0.5, dealbreaker_set_score: null },
  ],
  unknown_delta: 0,
  non_negotiable: null,
  is_bonus: false,
  position: 0,
  ...overrides,
});

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe("CriterionViewCard", () => {
  it("shows the label and one signed figure per option", () => {
    const { container } = wrap(<CriterionViewCard criterion={criterion()} entry={entry} />);
    expect(screen.getByText("Number of bedrooms")).toBeInTheDocument();
    const figures = [...container.querySelectorAll("tbody tr")].map(
      (row) => row.lastElementChild?.textContent,
    );
    expect(figures).toEqual(["+0.5", "0", "-0.5"]);
  });

  it("omits the unknown row when the unknown delta is zero", () => {
    wrap(<CriterionViewCard criterion={criterion()} entry={entry} />);
    expect(screen.queryByText("If unknown")).not.toBeInTheDocument();
  });

  it("shows the unknown row when it carries a delta", () => {
    wrap(<CriterionViewCard criterion={criterion({ unknown_delta: -0.25 })} entry={entry} />);
    expect(screen.getByText("If unknown")).toBeInTheDocument();
    expect(screen.getByText("-0.25")).toBeInTheDocument();
  });

  it("states the gate outcome and marks the card non-negotiable", () => {
    wrap(
      <CriterionViewCard
        criterion={criterion({ non_negotiable: { set_score: 0 } })}
        entry={entry}
      />,
    );
    expect(screen.getByText("If not met")).toBeInTheDocument();
    expect(screen.getByText("score → 0")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /non-negotiable/i })).toBeInTheDocument();
  });

  it("marks a bonus criterion, and only when every delta is non-negative", () => {
    const bonus = criterion({
      options: [{ match: { op: "eq", value: 2 }, delta: 0.5, dealbreaker_set_score: null }],
    });
    wrap(<CriterionViewCard criterion={bonus} entry={entry} />);
    expect(screen.getByRole("img", { name: /bonus criterion/i })).toBeInTheDocument();
  });

  it("does not mark a criterion that can dock points", () => {
    wrap(<CriterionViewCard criterion={criterion()} entry={entry} />);
    expect(screen.queryByRole("img", { name: /bonus criterion/i })).not.toBeInTheDocument();
  });

  it("renders a dealbreaker as its set score, with no bar", () => {
    const withDealbreaker = criterion({
      options: [
        { match: { op: "eq", value: 2 }, delta: 0.5, dealbreaker_set_score: null },
        { match: { op: "eq", value: 0 }, delta: 0, dealbreaker_set_score: 3 },
      ],
    });
    const { container } = wrap(<CriterionViewCard criterion={withDealbreaker} entry={entry} />);
    const row = screen.getByText("sets score to 3").closest("tr")!;
    expect(within(row).queryByText("+0")).not.toBeInTheDocument();
    // One bar per delta row; the dealbreaker row has none.
    expect(container.querySelectorAll("table tr")).toHaveLength(2);
  });
});
