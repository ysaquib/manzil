import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mutate, classifyMutate, showNotification } = vi.hoisted(() => ({
  mutate: vi.fn(),
  classifyMutate: vi.fn(),
  showNotification: vi.fn(),
}));

vi.mock("@mantine/notifications", () => ({
  notifications: { show: showNotification },
}));

vi.mock("../src/features/rubric/api", () => ({
  usePutRubric: () => ({ mutate, isPending: false }),
  useClassifyCustomRouting: () => ({ mutate: classifyMutate, isPending: false }),
}));

import type { CatalogEntry, RubricCriterion } from "../src/features/rubric/api";
import { RubricEditor } from "../src/features/rubric/RubricEditor";

const entry = (
  key: string,
  label: string,
  overrides: Partial<CatalogEntry> = {},
): CatalogEntry => ({
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
  ...overrides,
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
  beforeEach(() => {
    mutate.mockClear();
    classifyMutate.mockClear();
    showNotification.mockClear();
  });

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

  it("reports custom Criterion backfill work after saving", async () => {
    mutate.mockImplementation(
      (
        _payload: RubricCriterion[],
        callbacks: { onSuccess: (result: { backfillCount: number }) => void },
      ) => callbacks.onSuccess({ backfillCount: 3 }),
    );
    renderEditor();

    await userEvent.click(screen.getByRole("button", { name: "Save rubric" }));

    expect(showNotification).toHaveBeenCalledWith({
      title: "Backfilling 3 Listings",
      message: "Cached evidence is updating their scores. Follow progress in Tasks.",
      color: "violet",
    });
  });

  it("confirms routing before adding a custom criterion", async () => {
    classifyMutate.mockImplementation(
      (
        _body: unknown,
        callbacks: {
          onSuccess: (result: {
            key: string;
            suggested_requires_tool: null;
            reason: string;
            supported: boolean;
          }) => void;
        },
      ) =>
        callbacks.onSuccess({
          key: "custom:12345678-1234-1234-1234-123456789abc",
          suggested_requires_tool: null,
          reason: "The listing text can answer this.",
          supported: true,
        }),
    );
    renderEditor();

    await userEvent.click(screen.getByRole("button", { name: "Add custom criterion" }));
    await userEvent.type(await screen.findByLabelText("Name"), "Quiet hours");
    await userEvent.type(
      screen.getByLabelText("What should Manzil determine?"),
      "Whether the listing states quiet hours.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Suggest routing" }));

    expect(classifyMutate).toHaveBeenCalledTimes(1);
    expect(screen.getByText("The listing text can answer this.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm and add" }));

    expect(screen.getByLabelText("enable Quiet hours")).toBeChecked();
    expect(screen.getByText("2 of 4 criteria enabled")).toBeInTheDocument();
  });

  it("warns when objective flooring materials and subjective quality are both enabled", () => {
    const flooringCatalog = [
      entry("flooring_materials", "Flooring materials", {
        value_schema: {
          type: "array",
          items: {
            type: "string",
            enum: ["carpet", "hardwood", "engineered_wood", "laminate"],
          },
        },
        default_options: [
          {
            match: { op: "contains_any", value: ["hardwood", "engineered_wood"] },
            delta: 0.5,
            dealbreaker_set_score: null,
          },
        ],
      }),
      entry("flooring_quality", "Flooring quality", {
        value_schema: { type: "string", enum: ["low", "medium", "high"] },
        default_options: [
          { match: { op: "eq", value: "high" }, delta: 0.5, dealbreaker_set_score: null },
        ],
      }),
    ];
    const flooringSaved: RubricCriterion[] = flooringCatalog.map((catalogEntry, position) => ({
      catalog_key: catalogEntry.key,
      custom_def: null,
      enabled: true,
      options: catalogEntry.default_options,
      unknown_delta: 0,
      non_negotiable: null,
      is_bonus: true,
      position,
    }));

    render(
      <MantineProvider>
        <RubricEditor
          huntId="h1"
          catalog={flooringCatalog}
          saved={flooringSaved}
          onDone={vi.fn()}
        />
      </MantineProvider>,
    );

    expect(screen.getByText("Review overlapping options")).toBeInTheDocument();
    expect(screen.getByText(/avoid double-weighting flooring/)).toBeInTheDocument();
  });
});
