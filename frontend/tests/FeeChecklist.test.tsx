import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import { FeeChecklist } from "../src/features/listings/FeeChecklist";
import { ListingDetailDraftProvider } from "../src/features/listings/ListingDetailDraft";
import type { FeeEntry, Listing } from "../src/features/listings/types";

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

function renderFees(fees: FeeEntry[]) {
  return renderWithProviders(
    <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={fees}>
      <FeeChecklist fees={fees} />
    </ListingDetailDraftProvider>,
  );
}

const monthlyFee: FeeEntry = {
  hunt_listing_id: "listing-1",
  fee_slot: "water_sewer",
  amount: 50,
  value_state: "extracted",
  entered_by: null,
  evidence_ref: null,
  updated_at: null,
};

describe("FeeChecklist", () => {
  it("shows a fee with a flush amount and a state dot", () => {
    renderFees([monthlyFee]);
    expect(screen.getByText("$50")).toBeInTheDocument();
    expect(screen.getByTestId("fee-state-water_sewer")).toHaveAttribute(
      "data-state",
      "extracted",
    );
  });

  it("marks a manually entered fee with a manual dot and a revert affordance", () => {
    renderFees([{ ...monthlyFee, value_state: "manual", entered_by: "user-1" }]);
    expect(screen.getByTestId("fee-state-water_sewer")).toHaveAttribute(
      "data-state",
      "manual",
    );
    expect(
      screen.getByRole("button", { name: /revert Water \/ sewer billing/i }),
    ).toBeInTheDocument();
  });

  it("renders both slot sub-labels", () => {
    renderFees([]);
    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(screen.getByText("Move-in & one-time")).toBeInTheDocument();
  });
});
