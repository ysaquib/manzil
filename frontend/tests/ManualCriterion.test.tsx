// Manual custom Criteria (DESIGN §9.2): authored without a route, answered by
// hand on each Listing, stored as an ordinary Override.
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import type { ScoreBreakdown } from "../src/lib/contracts";
import { ListingDetailDraftProvider } from "../src/features/listings/ListingDetailDraft";
import { CriterionBreakdown } from "../src/features/listings/CriterionBreakdown";
import { manualCriteriaFor } from "../src/features/listings/ManualAnswerPanel";
import type { Listing, Override } from "../src/features/listings/types";
import type { CatalogEntry, CustomCriterionDef, RubricCriterion } from "../src/features/rubric/api";
import { customCatalogEntry } from "../src/features/rubric/customCriterion";

const MANUAL_KEY = "custom:11111111-1111-4111-8111-111111111111";
const TEXT_KEY = "custom:22222222-2222-4222-8222-222222222222";

const manualDef: CustomCriterionDef = {
  schema_version: 1,
  key: MANUAL_KEY,
  label: "Landlord was straight with us",
  description: "How the leasing agent came across on the phone.",
  fact_scope: "property",
  value_schema: { type: "string", enum: ["evasive", "fine", "great"] },
  acquisition: "manual",
  requires_tool: null,
  refresh_class: "manual",
  routing_confirmed: true,
};

const textDef: CustomCriterionDef = {
  schema_version: 1,
  key: TEXT_KEY,
  label: "Quiet hours",
  description: "Whether the listing states quiet hours.",
  fact_scope: "property",
  value_schema: { type: "boolean" },
  acquisition: "extracted",
  requires_tool: null,
  refresh_class: "listing_details",
  routing_confirmed: true,
};

function rubricRow(custom: CustomCriterionDef, enabled = true): RubricCriterion {
  return {
    catalog_key: null,
    custom_def: custom,
    enabled,
    options: [],
    unknown_delta: 0,
    non_negotiable: null,
    is_bonus: true,
    position: 0,
  };
}

const listingFixture = {
  id: "listing-1",
  hunt_id: "hunt-1",
  property_id: "prop-1",
  added_by: "u1",
  status: "active",
  pins: {},
} as unknown as Listing;

describe("manualCriteriaFor", () => {
  it("keeps only enabled manual Criteria", () => {
    const rubric = [
      rubricRow(manualDef),
      rubricRow(textDef),
      rubricRow({ ...manualDef, key: "custom:33333333-3333-4333-8333-333333333333" }, false),
    ];
    expect(manualCriteriaFor(rubric).map((c) => c.key)).toEqual([MANUAL_KEY]);
  });

  it("treats a definition with no acquisition as extracted", () => {
    const legacy = { ...manualDef, acquisition: undefined };
    expect(manualCriteriaFor([rubricRow(legacy)])).toEqual([]);
  });
});

describe("CriterionBreakdown manual state", () => {
  const catalog: CatalogEntry[] = [customCatalogEntry(manualDef), customCatalogEntry(textDef)];

  function renderBreakdown(breakdown: ScoreBreakdown, overrides: Override[] = []) {
    return renderWithProviders(
      <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
        <CriterionBreakdown
          huntId="hunt-1"
          listingId="listing-1"
          breakdown={breakdown}
          catalog={catalog}
          extractions={[]}
          overrides={overrides}
          floorPlanId={null}
          isMobile={false}
        />
      </ListingDetailDraftProvider>,
    );
  }

  const unansweredBoth: ScoreBreakdown = {
    base: 10,
    total: 10,
    rubric_version: 1,
    clamped: false,
    gates: [],
    criteria: [
      { key: MANUAL_KEY, value: null, matched: null, delta: 0, unknown: true },
      { key: TEXT_KEY, value: null, matched: null, delta: 0, unknown: true },
    ],
  };

  it("an unanswered manual Criterion asks for an answer", () => {
    renderBreakdown(unansweredBoth);
    expect(screen.getByText("Needs your answer")).toBeInTheDocument();
  });

  it("an unanswered extracted Criterion keeps the ordinary unknown state", () => {
    renderBreakdown(unansweredBoth);
    // One "Needs your answer" only — the text Criterion is unknown, not unanswered.
    expect(screen.getAllByText("Needs your answer")).toHaveLength(1);
    expect(screen.getByText("Quiet hours")).toBeInTheDocument();
  });

  it("an answered manual Criterion shows its value instead", () => {
    renderBreakdown({
      ...unansweredBoth,
      criteria: [
        { key: MANUAL_KEY, value: "great", matched: { op: "eq", value: "great" }, delta: 1 },
        { key: TEXT_KEY, value: null, matched: null, delta: 0, unknown: true },
      ],
    });
    expect(screen.queryByText("Needs your answer")).not.toBeInTheDocument();
  });
});

describe("CustomCriterionModal", () => {
  it("emits a manual definition and never calls the routing classifier", async () => {
    const classify = vi.fn();
    vi.resetModules();
    vi.doMock("../src/features/rubric/api", async (importOriginal) => {
      const actual = await importOriginal<typeof import("../src/features/rubric/api")>();
      return {
        ...actual,
        useClassifyCustomRouting: () => ({ mutate: classify, isPending: false, isError: false }),
      };
    });
    const { CustomCriterionModal } = await import(
      "../src/features/rubric/CustomCriterionModal"
    );

    const onAdd = vi.fn();
    renderWithProviders(
      <CustomCriterionModal huntId="hunt-1" opened onClose={() => {}} onAdd={onAdd} />,
    );

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "Landlord vibe");
    await user.type(
      screen.getByLabelText("What should Manzil determine?"),
      "How the agent came across.",
    );
    await user.click(screen.getByRole("radio", { name: "I answer it" }));

    // The routing step is gone entirely — there is no route to confirm.
    expect(screen.queryByText("Confirm routing")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suggest routing" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm and add" }));

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(classify).not.toHaveBeenCalled();
    const emitted = onAdd.mock.calls[0][0] as RubricCriterion;
    expect(emitted.custom_def).toMatchObject({
      acquisition: "manual",
      requires_tool: null,
      refresh_class: "manual",
      routing_confirmed: true,
      route_modifiers: null,
    });
    expect(emitted.custom_def?.key).toMatch(/^custom:[0-9a-f-]{36}$/);
    vi.doUnmock("../src/features/rubric/api");
  });
});
