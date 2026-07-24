import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Listing } from "../src/features/listings/types";

const data = vi.hoisted(() => ({ listings: [] as unknown[] }));

vi.mock("../src/features/listings/api", () => ({
  useListings: () => ({ data: data.listings, isLoading: false, error: null }),
  useUnitGroupStates: () => ({ data: [] }),
  usePropertyImages: () => ({ data: [], isLoading: false }),
}));

vi.mock("../src/features/rubric/api", () => ({
  useCatalog: () => ({
    data: [{ key: "in_unit_laundry", label: "In-unit laundry" }],
  }),
  useRubric: () => ({ data: [] }),
}));

import { ComparePage } from "../src/features/listings/ComparePage";

function makeListing(id: string, name: string, laundry: unknown): Listing {
  return {
    id,
    hunt_id: "h1",
    property_id: `${id}-prop`,
    added_by: "u1",
    status: "active",
    source_policy: "tiers_1_2_3",
    single_source_reason: null,
    pins: {},
    created_at: "2026-07-01T00:00:00Z",
    unavailable_at: null,
    all_in_components: null,
    property: {
      id: `${id}-prop`,
      name,
      canonical_address: "1 Main St",
      city: null,
      state: null,
      county: null,
      official_url: null,
      floor_plans: [
        {
          id: `${id}-plan`,
          property_id: `${id}-prop`,
          source_id: "src",
          plan_name: "A",
          beds: 2,
          baths: 2,
          sqft_min: 900,
          sqft_max: 900,
          rent_min: 1500,
          rent_max: 1600,
          deposit: 500,
          availability_date: "2026-08-01",
          available_units: 1,
        },
      ],
      sources: [],
    },
    scores: [
      {
        hunt_listing_id: id,
        floor_plan_id: `${id}-plan`,
        total: 11,
        breakdown: {
          base: 10,
          total: 11,
          rubric_version: 1,
          clamped: false,
          gates: [],
          criteria: [{ key: "in_unit_laundry", value: laundry, matched: null, delta: 1 }],
        },
        rubric_version: 1,
        computed_at: "2026-07-10T00:00:00Z",
      },
    ],
  };
}

function renderPage() {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={["/h/h1/compare"]}>
        <Routes>
          <Route path="/h/:huntId/compare" element={<ComparePage />} />
        </Routes>
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe("ComparePage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows the empty state when nothing was sent to compare", () => {
    data.listings = [];
    renderPage();
    expect(screen.getByText(/Send unit groups here/)).toBeInTheDocument();
  });

  it("renders one column per compared unit group with criteria rows", () => {
    data.listings = [makeListing("l1", "Beta Flats", "in_unit"), makeListing("l2", "Alpha Court", "on_site")];
    window.localStorage.setItem(
      "manzil:compare:h1",
      JSON.stringify([
        { listingId: "l1", groupKey: "2-2" },
        { listingId: "l2", groupKey: "2-2" },
      ]),
    );
    renderPage();
    expect(screen.getByText("Beta Flats")).toBeInTheDocument();
    expect(screen.getByText("Alpha Court")).toBeInTheDocument();
    expect(screen.getByText("Comparing 2 unit groups.")).toBeInTheDocument();
    expect(screen.getByText("In-unit laundry")).toBeInTheDocument();
    expect(screen.getByText("in unit")).toBeInTheDocument();
    expect(screen.getByText("on site")).toBeInTheDocument();
    expect(screen.getByText("Clear compare")).toBeInTheDocument();
  });
});
