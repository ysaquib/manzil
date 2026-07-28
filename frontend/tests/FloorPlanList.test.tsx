import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import type { PropertyImage } from "../src/features/listings/api";
import { FloorPlanList } from "../src/features/listings/FloorPlanList";
import { ListingDetailDraftProvider } from "../src/features/listings/ListingDetailDraft";
import type { Extraction, FloorPlan, Listing, Score } from "../src/features/listings/types";
import type { UnitGroupRow } from "../src/features/listings/unitGroups";
import type { CatalogEntry } from "../src/features/rubric/api";

const PRESENCE = ["confirmed", "advertised_unconfirmed", "none"];

const catalog: CatalogEntry[] = [
  {
    key: "patio_balcony",
    label: "Patio or balcony",
    category: "unit",
    domain: "rent",
    fact_scope: "floor_plan",
    value_schema: { type: "string", enum: PRESENCE },
    default_options: [],
    extraction_hint: "",
    requires_tool: null,
    refresh_class: "static",
  },
  {
    key: "dishwasher",
    label: "Dishwasher",
    category: "unit",
    domain: "rent",
    fact_scope: "floor_plan",
    value_schema: { type: "string", enum: PRESENCE },
    default_options: [],
    extraction_hint: "",
    requires_tool: null,
    refresh_class: "static",
  },
];

function plan(over: Partial<FloorPlan>): FloorPlan {
  return {
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
    deposit: 500,
    availability_date: "2026-08-01",
    available_units: 2,
    is_current: true,
    source_native_id: "FP-BIRCH",
    detail_url: "https://example.test/floorplans/birch",
    ...over,
  };
}

const birch = plan({});
const cedar = plan({ id: "plan-cedar", plan_name: "The Cedar", rent_min: 2100, rent_max: 2100 });

function score(planId: string, total: number): Score {
  return {
    hunt_listing_id: "listing-1",
    floor_plan_id: planId,
    total,
    breakdown: { base: 10, total, rubric_version: 1, clamped: false, gates: [], criteria: [] },
    rubric_version: 1,
    computed_at: "2026-07-08T00:00:00Z",
    all_in_components: null,
  };
}

const birchScore = score("plan-birch", 11);
const cedarScore = score("plan-cedar", 8);

const group: UnitGroupRow = {
  key: "1-1",
  beds: 1,
  baths: 1,
  unitTypes: ["apartment"],
  plans: [birch, cedar],
  scoredPlanCount: 2,
  displayPlan: birch,
  displayScore: birchScore,
  pinnedPlanId: null,
  rentMin: 1800,
  rentMax: 2100,
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
    lat: null,
    lng: null,
    floor_plans: [birch, cedar],
    sources: [
      {
        id: "src-1",
        property_id: "prop-1",
        url: "https://example.test/",
        site_domain: "example.test",
        is_official: true,
        last_fetched_at: null,
        last_success_at: "2026-07-26T18:02:00Z",
      },
    ],
  },
  scores: [birchScore, cedarScore],
};

const extractions: Extraction[] = [
  {
    id: "ex-1",
    property_id: "prop-1",
    hunt_id: null,
    criterion_key: "patio_balcony",
    record_kind: "resolved",
    origin_key: "page:1",
    target_scope: "floor_plan",
    floor_plan_id: "plan-birch",
    applicability: null,
    claim_group_id: "cg-1",
    value: "confirmed",
    confidence: "high",
    evidence_quote: "Private balcony in every Birch home.",
    source_id: "src-1",
    model: "gemini-3-flash-preview",
    resolution_rule: null,
    disputed: false,
    extracted_at: "2026-07-26T18:02:00Z",
  },
];

const diagram: PropertyImage = {
  id: "img-1",
  url: "https://signed.test/birch.webp",
  width: 2048,
  height: 1400,
  kind: "floor_plan_diagram",
  floorPlanAssociations: ["plan-birch"],
};

function renderList(images: PropertyImage[] = [diagram]) {
  return renderWithProviders(
    <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
      <FloorPlanList
        group={group}
        scores={[birchScore, cedarScore]}
        huntId="hunt-1"
        listingId="listing-1"
        catalog={catalog}
        extractions={extractions}
        overrides={[]}
        sources={listingFixture.property.sources}
        images={images}
        isMobile={false}
      />
    </ListingDetailDraftProvider>,
  );
}

describe("FloorPlanList — collapsed cards", () => {
  it("shows each plan's own score and amenity counts without opening anything", () => {
    renderList();

    expect(screen.getByTestId("plan-score-plan-birch")).toHaveTextContent("11");
    expect(screen.getByTestId("plan-score-plan-birch")).toHaveAttribute("data-band", "highest");
    expect(screen.getByTestId("plan-score-plan-cedar")).toHaveTextContent("8");

    // Birch: patio confirmed, dishwasher unknown. Cedar: both unknown.
    const birchCard = screen.getByTestId("plan-card-plan-birch");
    const summary = within(birchCard).getByLabelText("amenity summary");
    expect(summary).toHaveTextContent("1 confirmed");
    expect(summary).toHaveTextContent("1 unknown");
  });

  it("uses a dashed placeholder rather than a Property photo when no diagram is linked", () => {
    renderList();
    const cedarCard = screen.getByTestId("plan-card-plan-cedar");
    expect(
      within(cedarCard).getByRole("img", { name: "No floor plan diagram for The Cedar" }),
    ).toBeInTheDocument();
    expect(within(cedarCard).queryByAltText(/floor plan diagram$/)).not.toBeInTheDocument();

    const birchCard = screen.getByTestId("plan-card-plan-birch");
    expect(within(birchCard).getByAltText("The Birch floor plan diagram")).toBeInTheDocument();
  });

  it("never treats a Property photo as this plan's diagram", () => {
    renderList([{ ...diagram, kind: "listing_photo" }]);
    const birchCard = screen.getByTestId("plan-card-plan-birch");
    expect(
      within(birchCard).getByRole("img", { name: "No floor plan diagram for The Birch" }),
    ).toBeInTheDocument();
  });

  it("says which plan the Unit Group row is showing", () => {
    renderList();
    expect(screen.getByText(/No pin — showing best score:/)).toBeInTheDocument();
  });
});

describe("FloorPlanList — pin", () => {
  it("pins from the card without opening the detail", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Pin The Cedar for 1 bd / 1 ba" }));

    expect(screen.getByText(/^Pinned:/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Unpin The Cedar for 1 bd / 1 ba" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("unpins back to the best-scored plan", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Pin The Cedar for 1 bd / 1 ba" }));
    await user.click(screen.getByRole("button", { name: "Unpin The Cedar for 1 bd / 1 ba" }));

    expect(screen.getByText(/No pin — showing best score:/)).toBeInTheDocument();
  });
});

describe("FloorPlanList — detail modal", () => {
  it("opens the clicked plan's detail, not the Unit Group's display plan", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Cedar floor plan detail" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "The Cedar" })).toBeInTheDocument();
    expect(within(dialog).getByText("1 bd / 1 ba · 2 plans")).toBeInTheDocument();
  });

  it("states that no diagram was found instead of substituting one", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Cedar floor plan detail" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("No floor plan diagram found")).toBeInTheDocument();
  });

  it("groups amenities by presence and keeps unknowns visible", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Birch floor plan detail" }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getByText("Confirmed · 1")).toBeInTheDocument();
    expect(within(dialog).getByText("Unknown · 1")).toBeInTheDocument();
    expect(within(dialog).getByText("Patio or balcony")).toBeInTheDocument();
    expect(within(dialog).getByText("Dishwasher")).toBeInTheDocument();
  });

  it("keeps evidence behind a control and opens one at a time", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Birch floor plan detail" }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).queryByText(/Private balcony in every Birch home/)).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Evidence for Patio or balcony" }));
    expect(
      await within(dialog).findByText(/Private balcony in every Birch home/),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Evidence for Dishwasher" }));
    await waitFor(() =>
      expect(
        within(dialog).queryByText(/Private balcony in every Birch home/),
      ).not.toBeInTheDocument(),
    );
    expect(within(dialog).getByText(/No supporting text was found/)).toBeInTheDocument();
  });

  it("pins from the modal footer and reflects it on the card", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Cedar floor plan detail" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Pin for 1 bd / 1 ba" }));

    expect(await within(dialog).findByText("Pinned for 1 bd / 1 ba")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Unpin The Cedar for 1 bd / 1 ba" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("returns to the Unit Group from the header crumb", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Birch floor plan detail" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /1 bd \/ 1 ba · 2 plans/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  // The drawer-scoped overlay is the whole point of the desktop presentation:
  // Mantine's Modal is viewport-fixed by default, and a CSS Module class loses
  // the cascade to Mantine's own slot rules. Pin the inline overrides so a
  // future refactor can't silently send the overlay back to full-viewport.
  it("anchors the overlay to the drawer column on desktop", async () => {
    const user = userEvent.setup();
    const { container } = renderList();

    await user.click(screen.getByRole("button", { name: "Open The Birch floor plan detail" }));
    await screen.findByRole("dialog");

    const overlay = container.querySelector<HTMLElement>(".mantine-Modal-overlay");
    const inner = container.querySelector<HTMLElement>(".mantine-Modal-inner");
    expect(overlay?.style.position).toBe("absolute");
    expect(overlay?.style.inset).toMatch(/^0/);
    expect(inner?.style.position).toBe("absolute");
    expect(inner?.style.inset).toMatch(/^0/);
  });

  it("goes full-screen on phones instead of scoping to the drawer", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(
      <ListingDetailDraftProvider huntId="hunt-1" listing={listingFixture} serverFees={[]}>
        <FloorPlanList
          group={group}
          scores={[birchScore, cedarScore]}
          huntId="hunt-1"
          listingId="listing-1"
          catalog={catalog}
          extractions={extractions}
          overrides={[]}
          sources={listingFixture.property.sources}
          images={[diagram]}
          isMobile
        />
      </ListingDetailDraftProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Open The Birch floor plan detail" }));
    await screen.findByRole("dialog");

    const overlay = container.querySelector<HTMLElement>(".mantine-Modal-overlay");
    expect(overlay?.style.position).toBe("");
    expect(container.querySelector('[data-full-screen="true"]')).not.toBeNull();
  });

  it("links out to the plan's own Source URL", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open The Birch floor plan detail" }));
    const dialog = await screen.findByRole("dialog");
    const link = within(dialog).getByRole("link", { name: /Open full-size on example.test/ });
    expect(link).toHaveAttribute("href", "https://example.test/floorplans/birch");
  });
});
