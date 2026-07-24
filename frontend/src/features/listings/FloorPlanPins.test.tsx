import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../../../tests/testUtils";
import { FloorPlanPins } from "./FloorPlanPins";
import { ListingDetailDraftProvider } from "./ListingDetailDraft";
import type { FloorPlan, Listing, Score } from "./types";
import type { UnitGroupRow } from "./unitGroups";

const birch: FloorPlan = {
  id: "plan-birch",
  property_id: "prop-1",
  source_id: "src-1",
  plan_name: "The Birch",
  beds: 1,
  baths: 1,
  unit_types: ["apartment"],
  sqft_min: 700,
  sqft_max: 750,
  rent_min: 1800,
  rent_max: 1950,
  deposit: null,
  availability_date: "2026-08-01",
  available_units: 2,
  is_current: true,
};

const birchScore: Score = {
  hunt_listing_id: "listing-1",
  floor_plan_id: "plan-birch",
  total: 11,
  breakdown: { base: 10, total: 11, rubric_version: 1, clamped: false, gates: [], criteria: [] },
  rubric_version: 1,
  computed_at: "2026-07-08T00:00:00Z",
  all_in_components: null,
};

const group: UnitGroupRow = {
  key: "1-1",
  beds: 1,
  baths: 1,
  unitTypes: ["apartment"],
  plans: [birch],
  scoredPlanCount: 1,
  displayPlan: birch,
  displayScore: birchScore,
  pinnedPlanId: null,
  rentMin: 1800,
  rentMax: 1950,
  sqftMin: 700,
  sqftMax: 750,
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
    floor_plans: [birch],
    sources: [],
  },
  scores: [birchScore],
};

function renderPins() {
  return renderWithProviders(
    <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
      <FloorPlanPins group={group} scores={[birchScore]} />
    </ListingDetailDraftProvider>,
  );
}

describe("FloorPlanPins", () => {
  it("shows each plan's score chip on the name line", () => {
    renderPins();
    expect(screen.getByText("11")).toBeInTheDocument(); // formatScore(11)
    expect(screen.getByText("The Birch")).toBeInTheDocument();

    // The chip is band-colored (11/10 → highest) and sits WITH the plan name,
    // not in a separate right column. (CSS modules are disabled in tests, so
    // the band is exposed via data-band — mirrors FeeChecklist's data-state.)
    const chip = screen.getByTestId("plan-score-plan-birch");
    expect(chip).toHaveTextContent("11");
    expect(chip).toHaveAttribute("data-band", "highest");
    expect(screen.getByText("The Birch").parentElement).toContainElement(chip);
  });
});
