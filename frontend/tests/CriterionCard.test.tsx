// CriterionCard's mobile contract (UI Decision Log 2026-08-11).
//
// The sub-`48em` reflow is pure CSS, so what a jsdom test can protect is the
// structure that CSS depends on and the copy that touch depends on:
//
//  1. Every option row hands OptionGridRow exactly three children. The mobile
//     branch spans the *first* cell across the row, so a row with two children
//     loses its points column and one with four wraps a stray cell onto a
//     second line — which is what the old `<div />` padding did, silently.
//  2. A dealbreaker and an armed gate state their consequence as visible text,
//     not only as a tooltip. There is no hover on a phone.
import { MantineProvider } from "@mantine/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CatalogEntry, RubricCriterion } from "../src/features/rubric/api";
import { CriterionCard } from "../src/features/rubric/CriterionCard";

const numericEntry: CatalogEntry = {
  key: "rent",
  label: "Base rent",
  category: "money",
  domain: "rent",
  fact_scope: "floor_plan",
  value_schema: { type: "number" },
  default_options: [],
  extraction_hint: "the advertised monthly rent",
  requires_tool: null,
  refresh_class: "volatile",
};

const boolEntry: CatalogEntry = {
  ...numericEntry,
  key: "in_unit_laundry",
  label: "In-unit laundry",
  value_schema: { type: "boolean" },
};

const criterion = (overrides: Partial<RubricCriterion> = {}): RubricCriterion => ({
  catalog_key: "rent",
  custom_def: null,
  enabled: true,
  options: [
    { match: { op: "lte", value: 1800 }, delta: 2, dealbreaker_set_score: null },
    { match: { op: "lte", value: 2200 }, delta: 0.5, dealbreaker_set_score: null },
  ],
  unknown_delta: -1,
  non_negotiable: null,
  is_bonus: false,
  position: 0,
  ...overrides,
});

function renderCard(c: RubricCriterion, entry: CatalogEntry = numericEntry) {
  const onChange = vi.fn();
  const view = render(
    <MantineProvider>
      <CriterionCard criterion={c} entry={entry} onChange={onChange} />
    </MantineProvider>,
  );
  return { ...view, onChange };
}

const rowsIn = (container: HTMLElement) =>
  [...container.querySelectorAll<HTMLElement>("[data-option-row]")];

describe("CriterionCard — grid row contract", () => {
  it("gives every row exactly three cells, so the mobile reflow has fixed tracks", () => {
    const { container } = renderCard(criterion());
    const rows = rowsIn(container);

    // header + two options + unknown + gate
    expect(rows).toHaveLength(5);
    for (const row of rows) {
      expect(row.children).toHaveLength(3);
    }
  });

  it("holds the contract for boolean criteria, which render fixed True/False rows", () => {
    const { container } = renderCard(
      criterion({
        catalog_key: "in_unit_laundry",
        options: [{ match: { op: "bool", value: true }, delta: 1, dealbreaker_set_score: null }],
      }),
      boolEntry,
    );
    const rows = rowsIn(container);

    // header + True + False + unknown + gate
    expect(rows).toHaveLength(5);
    for (const row of rows) {
      expect(row.children).toHaveLength(3);
    }
  });

  it("holds the contract once a gate is armed and its set-score appears", async () => {
    const { container } = renderCard(criterion({ non_negotiable: { set_score: 0 } }));

    expect(screen.getByLabelText("non-negotiable set score")).toBeInTheDocument();
    for (const row of rowsIn(container)) {
      expect(row.children).toHaveLength(3);
    }
  });

  it("keeps three cells when a dealbreaker swaps the points input", async () => {
    const { container } = renderCard(
      criterion({
        options: [{ match: { op: "lte", value: 1800 }, delta: 0, dealbreaker_set_score: 0 }],
      }),
    );

    expect(screen.getByLabelText("dealbreaker set score")).toBeInTheDocument();
    for (const row of rowsIn(container)) {
      expect(row.children).toHaveLength(3);
    }
  });

  it("marks the column-heading row so mobile can drop it", () => {
    const { container } = renderCard(criterion());
    const headers = container.querySelectorAll('[data-option-row="header"]');

    expect(headers).toHaveLength(1);
    expect(within(headers[0] as HTMLElement).getByText("Points")).toBeInTheDocument();
  });
});

describe("CriterionCard — consequences readable without hover", () => {
  it("states what a dealbreaker does, in text, whenever one is armed", () => {
    renderCard(
      criterion({
        options: [{ match: { op: "lte", value: 1800 }, delta: 0, dealbreaker_set_score: 3 }],
      }),
    );

    expect(
      screen.getByText("Matching this sets the listing's score to 3 instead of adding points."),
    ).toBeInTheDocument();
  });

  it("says nothing extra while every option scores points normally", () => {
    renderCard(criterion());
    expect(screen.queryByText(/instead of adding points/)).not.toBeInTheDocument();
  });

  it("states the gate's consequence in text once it is switched on", async () => {
    const { onChange } = renderCard(criterion());

    expect(screen.queryByText(/Not met sets the listing's score/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Non-negotiable"));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ non_negotiable: { set_score: 0 } }),
    );
  });

  it("renders the gate's consequence for an already-armed gate", () => {
    renderCard(criterion({ non_negotiable: { set_score: 2 } }));
    expect(
      screen.getByText("Not met sets the listing's score to 2 instead of adding points."),
    ).toBeInTheDocument();
  });
});

describe("CriterionCard — modified indicator, revert, and inline issues", () => {
  it("shows no Modified indicator when not dirty, and one with a working revert when dirty", async () => {
    const onRevert = vi.fn();
    const { rerender } = render(
      <MantineProvider>
        <CriterionCard
          criterion={criterion()}
          entry={numericEntry}
          onChange={vi.fn()}
          onRevert={onRevert}
          dirty={false}
        />
      </MantineProvider>,
    );
    expect(screen.queryByText("Modified")).not.toBeInTheDocument();

    rerender(
      <MantineProvider>
        <CriterionCard
          criterion={criterion()}
          entry={numericEntry}
          onChange={vi.fn()}
          onRevert={onRevert}
          dirty={true}
        />
      </MantineProvider>,
    );
    expect(screen.getByText("Modified")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("revert to saved"));
    expect(onRevert).toHaveBeenCalledWith("rent");
  });

  it("renders save-time issues scoped to this criterion", () => {
    render(
      <MantineProvider>
        <CriterionCard
          criterion={criterion()}
          entry={numericEntry}
          onChange={vi.fn()}
          issues={[{ catalogKey: "rent", message: "option 1: expected a number" }]}
        />
      </MantineProvider>,
    );
    expect(screen.getByText("option 1: expected a number")).toBeInTheDocument();
  });

  it("calls onRemove with the entry's key, not a bare event handler", async () => {
    const onRemove = vi.fn();
    render(
      <MantineProvider>
        <CriterionCard
          criterion={criterion()}
          entry={numericEntry}
          onChange={vi.fn()}
          onRemove={onRemove}
        />
      </MantineProvider>,
    );
    await userEvent.click(screen.getByLabelText("remove Base rent"));
    expect(onRemove).toHaveBeenCalledWith("rent");
  });
});
