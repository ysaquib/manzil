// The drawer's "Your answers" panel — the collected entry point for manual
// custom Criteria, which have no producer and are only ever answered by hand.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import { ListingDetailDraftProvider } from "../src/features/listings/ListingDetailDraft";
import { ManualAnswerPanel } from "../src/features/listings/ManualAnswerPanel";
import type { Listing, Override } from "../src/features/listings/types";
import type { CustomCriterionDef, RubricCriterion } from "../src/features/rubric/api";

const MANUAL_KEY = "custom:11111111-1111-4111-8111-111111111111";
const PLAN_KEY = "custom:44444444-4444-4444-8444-444444444444";

const rubricRows = vi.hoisted(() => ({ current: [] as unknown[] }));

vi.mock("../src/features/rubric/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/features/rubric/api")>();
  return { ...actual, useRubric: () => ({ data: rubricRows.current }) };
});

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

const planScopedDef: CustomCriterionDef = {
  ...manualDef,
  key: PLAN_KEY,
  label: "Natural light in the unit",
  description: "How the unit felt on the tour.",
  fact_scope: "floor_plan",
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

function renderPanel(overrides: Override[] = [], floorPlanId: string | null = null) {
  return renderWithProviders(
    <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
      <ManualAnswerPanel huntId="hunt-1" overrides={overrides} floorPlanId={floorPlanId} />
    </ListingDetailDraftProvider>,
  );
}

describe("ManualAnswerPanel", () => {
  beforeEach(() => {
    rubricRows.current = [];
  });

  it("renders nothing when the Hunt has no manual Criteria", () => {
    rubricRows.current = [rubricRow({ ...manualDef, acquisition: "extracted" })];
    renderPanel();
    expect(
      screen.queryByText("Only you can answer these — nothing is read off the listing."),
    ).not.toBeInTheDocument();
  });

  it("lists enabled manual Criteria with an unanswered count", () => {
    rubricRows.current = [rubricRow(manualDef), rubricRow(planScopedDef, false)];
    renderPanel();
    expect(screen.getByText("Landlord was straight with us")).toBeInTheDocument();
    expect(screen.queryByText("Natural light in the unit")).not.toBeInTheDocument();
    expect(screen.getByText("0 of 1")).toBeInTheDocument();
  });

  it("counts a saved Override as answered", () => {
    rubricRows.current = [rubricRow(manualDef)];
    const override = {
      id: "o1",
      hunt_listing_id: "listing-1",
      criterion_key: MANUAL_KEY,
      value: "great",
      target_scope: "property",
      floor_plan_id: null,
      applicability: null,
      user_id: "u1",
      note: null,
      created_at: new Date().toISOString(),
    } as unknown as Override;
    renderPanel([override]);
    expect(screen.getByText("1 of 1")).toBeInTheDocument();
  });

  it("answering stages a draft Override and updates the count", async () => {
    rubricRows.current = [rubricRow(manualDef)];
    renderPanel();
    const user = userEvent.setup();

    // Mantine's Select associates the label with both the visible and hidden inputs.
    await user.click(screen.getAllByLabelText("Landlord was straight with us")[0]);
    await user.click(await screen.findByRole("option", { name: "great", hidden: true }));

    expect(screen.getByText("1 of 1")).toBeInTheDocument();
  });

  it("a Floor Plan-scoped Criterion cannot be answered without a Floor Plan", () => {
    rubricRows.current = [rubricRow(planScopedDef)];
    renderPanel([], null);
    expect(screen.getByText("Pick a Floor Plan above to answer this one.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Natural light in the unit")).not.toBeInTheDocument();
  });
});
