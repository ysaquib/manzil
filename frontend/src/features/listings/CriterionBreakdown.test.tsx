import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../../../tests/testUtils";
import type { ScoreBreakdown } from "../../lib/contracts";
import { ListingDetailDraftProvider } from "./ListingDetailDraft";
import { CriterionBreakdown } from "./CriterionBreakdown";
import type { Extraction, Listing, Override } from "./types";
import type { CatalogEntry } from "../rubric/api";

const catalog: CatalogEntry[] = [
  {
    key: "beds",
    label: "Number of bedrooms",
    category: "unit",
    domain: "rent",
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
    value_schema: { type: "string", enum: ["in_unit", "hookups", "on_site", "none"] },
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
  value: 3,
  confidence: "high",
  evidence_quote: "Three spacious bedrooms",
  source_id: null,
  model: "test-model",
  resolution_rule: null,
  extracted_at: "2026-07-01T00:00:00Z",
};

const override: Override = {
  id: "ov-1",
  hunt_listing_id: "listing-1",
  criterion_key: "beds",
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
  pins: {},
  created_at: "2026-07-08T00:00:00Z",
  unavailable_at: null,
  property: {
    id: "prop-1",
    name: "Test",
    canonical_address: "1 Main",
    official_url: null,
    floor_plans: [],
    sources: [],
  },
  scores: [],
};

function renderBreakdown(breakdown: ScoreBreakdown, overrides: Override[] = []) {
  return renderWithProviders(
    <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
      <CriterionBreakdown
        huntId="hunt-1"
        listingId="listing-1"
        breakdown={breakdown}
        catalog={catalog}
        extractions={new Map([["beds", extraction]])}
        overrides={overrides}
        isMobile={false}
      />
    </ListingDetailDraftProvider>,
  );
}

describe("CriterionBreakdown", () => {
  it("renders criteria rows with catalog labels and deltas", () => {
    renderBreakdown(normalBreakdown);
    expect(screen.getByText("Number of bedrooms")).toBeInTheDocument();
    expect(screen.getByText("+0.5")).toBeInTheDocument();
    expect(screen.getByText("-1")).toBeInTheDocument();
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });

  it("says a gate fired instead of showing a hollow list (§9.3)", () => {
    renderBreakdown(gatedBreakdown);
    expect(screen.getByText(/gate fired/i)).toBeInTheDocument();
    expect(screen.getByText(/failed a non-negotiable/)).toBeInTheDocument();
    expect(screen.getByText(/score set to 0/)).toBeInTheDocument();
    expect(screen.queryByText("Number of bedrooms")).not.toBeInTheDocument();
  });

  it("marks overridden criteria with the override badge (§9.6 precedence)", () => {
    renderBreakdown(normalBreakdown, [override]);
    expect(screen.getByText("override")).toBeInTheDocument();
  });

  it("shows no override badge without overrides", () => {
    renderBreakdown(normalBreakdown);
    expect(screen.queryByText("override")).not.toBeInTheDocument();
  });
});
