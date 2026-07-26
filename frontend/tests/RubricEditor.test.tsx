import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mutate } = vi.hoisted(() => ({ mutate: vi.fn() }));

vi.mock("../src/features/rubric/api", () => ({
  usePutRubric: () => ({ mutate, isPending: false }),
}));

import type { CatalogEntry, RubricCriterion } from "../src/features/rubric/api";
import { RubricEditor } from "../src/features/rubric/RubricEditor";

const entry = (key: string, label: string): CatalogEntry => ({
  key,
  label,
  category: "unit",
  domain: "rent",
  fact_scope: "floor_plan",
  value_schema: { type: "number" },
  default_options: [{ match: { op: "eq", value: 1 }, delta: 0.5, dealbreaker_set_score: null }],
  extraction_hint: "how this is read off the page",
  requires_tool: null,
  refresh_class: "static",
});

const catalog = [
  entry("beds", "Number of bedrooms"),
  entry("sqft", "Square footage"),
  entry("parking", "Parking"),
];

const saved: RubricCriterion[] = [
  {
    catalog_key: "beds",
    custom_def: null,
    enabled: true,
    options: [{ match: { op: "eq", value: 2 }, delta: 0.5, dealbreaker_set_score: null }],
    unknown_delta: 0,
    non_negotiable: null,
    is_bonus: true,
    position: 0,
  },
];

function renderEditor() {
  return render(
    <MantineProvider>
      <RubricEditor huntId="h1" catalog={catalog} saved={saved} onDone={vi.fn()} />
    </MantineProvider>,
  );
}

describe("RubricEditor", () => {
  beforeEach(() => mutate.mockClear());

  it("cards the scored criteria and offers the rest as add-pills", () => {
    renderEditor();
    expect(screen.getByLabelText("enable Number of bedrooms")).toBeChecked();
    expect(screen.getByRole("button", { name: "Square footage" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Parking" })).toBeInTheDocument();
    // A criterion that is scored has a card, not a pill.
    expect(screen.queryByRole("button", { name: "Number of bedrooms" })).not.toBeInTheDocument();
  });

  it("turns a pill into a scored card, and the card's switch turns it back", async () => {
    renderEditor();

    await userEvent.click(screen.getByRole("button", { name: "Square footage" }));
    expect(screen.getByLabelText("enable Square footage")).toBeChecked();
    expect(screen.queryByRole("button", { name: "Square footage" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("enable Square footage"));
    expect(screen.getByRole("button", { name: "Square footage" })).toBeInTheDocument();
  });

  it("counts scored criteria per category and overall", async () => {
    renderEditor();
    expect(screen.getByText("1 of 3 criteria enabled")).toBeInTheDocument();
    expect(screen.getByText("1 of 3")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Parking" }));
    expect(screen.getByText("2 of 3 criteria enabled")).toBeInTheDocument();
  });

  // The picker only changes what is *rendered*; the draft still carries every
  // catalog entry, and the API relies on that (a criterion dropped from the
  // payload is not the same as one saved disabled).
  it("saves every criterion, scored or not", async () => {
    renderEditor();

    await userEvent.click(screen.getByRole("button", { name: "Square footage" }));
    await userEvent.click(screen.getByRole("button", { name: "Save rubric" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const payload = mutate.mock.calls[0][0] as RubricCriterion[];
    expect(payload.map((c) => [c.catalog_key, c.enabled, c.position])).toEqual([
      ["beds", true, 0],
      ["sqft", true, 1],
      ["parking", false, 2],
    ]);
  });
});
