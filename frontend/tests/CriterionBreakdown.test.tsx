import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import type { ScoreBreakdown } from "../src/lib/contracts";
import { ListingDetailDraftProvider } from "../src/features/listings/ListingDetailDraft";
import { CriterionBreakdown } from "../src/features/listings/CriterionBreakdown";
import type { Extraction, Listing, Override } from "../src/features/listings/types";
import type { CatalogEntry } from "../src/features/rubric/api";

const catalog: CatalogEntry[] = [
  {
    key: "beds",
    label: "Number of bedrooms",
    category: "unit",
    domain: "rent",
    fact_scope: "floor_plan",
    value_schema: { type: "integer", minimum: 0, maximum: 5 },
    default_options: [],
    extraction_hint: "",
    requires_tool: null,
    refresh_class: "listing_details",
  },
  {
    key: "in_unit_laundry",
    label: "In-unit laundry",
    category: "unit",
    domain: "rent",
    fact_scope: "mixed",
    value_schema: { type: "string", enum: ["in_unit", "hookups", "on_site", "none"] },
    default_options: [],
    extraction_hint: "",
    requires_tool: null,
    refresh_class: "listing_details",
  },
  {
    key: "pool",
    label: "Pool",
    category: "property",
    domain: "rent",
    fact_scope: "property",
    value_schema: { type: "string", enum: ["outdoor", "none"] },
    default_options: [],
    extraction_hint: "",
    requires_tool: null,
    refresh_class: "listing_details",
  },
];

const normalBreakdown: ScoreBreakdown = {
  base: 10,
  total: 9.5,
  rubric_version: 1,
  clamped: false,
  gates: [],
  criteria: [
    { key: "beds", value: 2, matched: { op: "eq", value: 2 }, delta: 0.5 },
    { key: "in_unit_laundry", value: null, matched: null, delta: -1.0, unknown: true },
  ],
};

const scopedBreakdown: ScoreBreakdown = {
  ...normalBreakdown,
  criteria: [
    { key: "pool", value: "outdoor", matched: { op: "eq", value: "outdoor" }, delta: 0.25 },
    ...normalBreakdown.criteria,
  ],
};

// §9.3: when a gate fires, criteria is empty and total is the min set-score.
const gatedBreakdown: ScoreBreakdown = {
  base: 10,
  total: 0,
  rubric_version: 1,
  clamped: false,
  gates: [{ key: "in_unit_laundry", kind: "non_negotiable", set_score: 0 }],
  criteria: [],
};

const extraction: Extraction = {
  id: "ex-1",
  property_id: "prop-1",
  hunt_id: null,
  criterion_key: "beds",
  record_kind: "resolved",
  origin_key: "resolution:test",
  target_scope: "property",
  floor_plan_id: null,
  applicability: "unit_scope_unspecified",
  claim_group_id: "cg-1",
  value: 3,
  confidence: "high",
  evidence_quote: "Three spacious bedrooms",
  source_id: null,
  model: "test-model",
  resolution_rule: null,
  disputed: false,
  extracted_at: "2026-07-01T00:00:00Z",
};

const override: Override = {
  id: "ov-1",
  hunt_listing_id: "listing-1",
  criterion_key: "beds",
  target_scope: "property",
  floor_plan_id: null,
  applicability: null,
  value: 2,
  user_id: "user-1",
  note: null,
  created_at: "2026-07-02T00:00:00Z",
};

const listingFixture: Listing = {
  id: "listing-1",
  hunt_id: "hunt-1",
  property_id: "prop-1",
  added_by: "user-1",
  status: "active",
      source_policy: "tiers_1_2_3",
      single_source_reason: null,
  pins: {},
  created_at: "2026-07-08T00:00:00Z",
  unavailable_at: null,
  all_in_components: null,
  property: {
    id: "prop-1",
    name: "Test",
    canonical_address: "1 Main",
    city: null,
    state: null,
    county: null,
    official_url: null,
    lat: null,
    lng: null,
    floor_plans: [],
    sources: [],
  },
  scores: [],
};

function renderBreakdown(
  breakdown: ScoreBreakdown,
  overrides: Override[] = [],
  extractions: Extraction[] = [extraction],
  catalogEntries: CatalogEntry[] = catalog,
) {
  return renderWithProviders(
    <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
      <CriterionBreakdown
        huntId="hunt-1"
        listingId="listing-1"
        breakdown={breakdown}
        catalog={catalogEntries}
        extractions={extractions}
        overrides={overrides}
        floorPlanId={null}
        isMobile={false}
      />
    </ListingDetailDraftProvider>,
  );
}

describe("CriterionBreakdown", () => {
  it("renders criteria rows with catalog labels and deltas", () => {
    renderBreakdown(normalBreakdown);
    expect(screen.getByText("Number of bedrooms")).toBeInTheDocument();
    expect(screen.getByText("+0.50")).toBeInTheDocument();
    expect(screen.getByText("-1.00")).toBeInTheDocument();
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });

  it("separates Property facts from Floor Plan facts and renders each Property fact once", () => {
    renderBreakdown(scopedBreakdown);
    expect(screen.getByText("Property facts")).toBeInTheDocument();
    expect(screen.getByText("Floor plan facts")).toBeInTheDocument();
    expect(screen.getAllByText("Pool")).toHaveLength(1);
  });

  it("says a gate fired instead of showing a hollow list (§9.3)", () => {
    renderBreakdown(gatedBreakdown);
    expect(screen.getByText(/gate fired/i)).toBeInTheDocument();
    expect(screen.getByText(/failed a non-negotiable/)).toBeInTheDocument();
    expect(screen.getByText(/score set to 0/)).toBeInTheDocument();
    expect(screen.queryByText("Number of bedrooms")).not.toBeInTheDocument();
  });

  it("marks overridden criteria with the override affordance (§9.6 precedence)", () => {
    // The word badge became a quiet plum dot + a revert affordance.
    renderBreakdown(normalBreakdown, [override]);
    expect(screen.getByLabelText("overridden")).toBeInTheDocument();
    expect(screen.getByLabelText("revert beds override")).toBeInTheDocument();
  });

  it("shows no override affordance without overrides", () => {
    renderBreakdown(normalBreakdown);
    expect(screen.queryByLabelText("overridden")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/revert/)).not.toBeInTheDocument();
  });

  it("quietly labels generalized applicability and disagreement", () => {
    // Applicability + disagreement collapse into one quiet text flag.
    renderBreakdown(normalBreakdown, [], [{ ...extraction, disputed: true }]);
    expect(screen.getByText(/units unspecified/)).toBeInTheDocument();
    expect(screen.getByText(/sources disagree/)).toBeInTheDocument();
  });

  // P3-8 (DESIGN §20 2026-07-18): location_safety is an override-first
  // placeholder — an unknown renders as "awaiting grade", never bare.
  it("frames unknown location_safety as awaiting a grade", () => {
    const withSafety: ScoreBreakdown = {
      ...normalBreakdown,
      criteria: [
        ...normalBreakdown.criteria,
        { key: "location_safety", value: null, matched: null, delta: 0, unknown: true },
      ],
    };
    renderBreakdown(withSafety);
    expect(screen.getByText("awaiting grade")).toBeInTheDocument();
  });

  it("does not show the awaiting-grade badge once safety has a value", () => {
    const graded: ScoreBreakdown = {
      ...normalBreakdown,
      criteria: [
        ...normalBreakdown.criteria,
        { key: "location_safety", value: "B+", matched: { op: "eq", value: "B+" }, delta: 0.25 },
      ],
    };
    renderBreakdown(graded);
    expect(screen.queryByText("awaiting grade")).not.toBeInTheDocument();
    expect(screen.getByText("B+")).toBeInTheDocument();
  });

  it("shows the baseline, a signed delta per criterion, and the total out of 15", () => {
    const breakdown: ScoreBreakdown = {
      base: 10,
      total: 12.5,
      rubric_version: 1,
      clamped: false,
      gates: [],
      criteria: [{ key: "pets", value: "cats_dogs", matched: null, delta: 1.5 }],
    };
    renderBreakdown(breakdown);
    expect(screen.getByText("Baseline")).toBeInTheDocument();
    expect(screen.getByText("10.0")).toBeInTheDocument();
    expect(screen.getByText("+1.50")).toBeInTheDocument();
    expect(screen.getByText(/12\.5/)).toBeInTheDocument();
    expect(screen.getByText("/ 15")).toBeInTheDocument();
  });

  it("renders one evidence affordance per criterion that has an extraction", () => {
    const breakdown: ScoreBreakdown = {
      base: 10,
      total: 11,
      rubric_version: 1,
      clamped: false,
      gates: [],
      criteria: [{ key: "pets", value: "cats_dogs", matched: null, delta: 1 }],
    };
    renderBreakdown(breakdown, [], [{ ...extraction, criterion_key: "pets" }]);
    expect(screen.getAllByLabelText("evidence")).toHaveLength(1);
  });

  it("shows custom criterion label from merged catalog, not opaque key", () => {
    const customKey = "custom:550e8400-e29b-41d4-a716-446655440000";
    const mergedCatalog: CatalogEntry[] = [
      ...catalog,
      {
        key: customKey,
        label: "Near grocery store",
        category: "custom",
        domain: "rent",
        fact_scope: "property",
        value_schema: { type: "number" },
        default_options: [],
        extraction_hint: "",
        requires_tool: "maps",
        refresh_class: "location",
      },
    ];
    const breakdown: ScoreBreakdown = {
      base: 10,
      total: 10.5,
      rubric_version: 1,
      clamped: false,
      gates: [],
      criteria: [{ key: customKey, value: 8, matched: null, delta: 0.5 }],
    };
    renderBreakdown(breakdown, [], [], mergedCatalog);
    expect(screen.getByText("Near grocery store")).toBeInTheDocument();
    expect(screen.queryByText(customKey)).not.toBeInTheDocument();
  });

  it("opens evidence in a popover on mobile", async () => {
    const user = userEvent.setup();
    const breakdown: ScoreBreakdown = {
      base: 10,
      total: 11,
      rubric_version: 1,
      clamped: false,
      gates: [],
      criteria: [{ key: "pets", value: "cats_dogs", matched: null, delta: 1 }],
    };
    renderWithProviders(
      <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
        <CriterionBreakdown
          huntId="hunt-1"
          listingId="listing-1"
          breakdown={breakdown}
          catalog={catalog}
          extractions={[{ ...extraction, criterion_key: "pets" }]}
          overrides={[]}
          floorPlanId={null}
          isMobile
        />
      </ListingDetailDraftProvider>,
    );
    await user.click(screen.getByLabelText("evidence"));
    expect(await screen.findByText(/confidence/)).toBeInTheDocument();
  });
});
