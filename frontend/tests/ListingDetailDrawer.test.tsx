import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Listing } from "../src/features/listings/types";

const data = vi.hoisted(() => ({ listings: [] as unknown[] }));

vi.mock("../src/auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: "u1" } } }),
}));

vi.mock("../src/features/listings/api", () => {
  const mut = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  return {
    useListings: () => ({ data: data.listings, isLoading: false, error: null }),
    useFees: () => ({ data: [] }),
    useExtractions: () => ({ data: [], isLoading: false }),
    useOverrides: () => ({ data: [] }),
    usePropertyImages: () => ({ data: [], isLoading: false }),
    usePatchPins: mut,
    useCreateOverride: mut,
    useUpsertFee: mut,
    usePatchSourcePolicy: mut,
  };
});

vi.mock("../src/features/collaboration/api", () => {
  const mut = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  return {
    useMembers: () => ({ data: [] }),
    useCurrentMember: () => ({ data: { user_id: "u1", role: "owner", color: "moss" } }),
    useComments: () => ({ data: [] }),
    useRatings: () => ({ data: [] }),
    useSetRating: mut,
    useCreateComment: mut,
    useUpdateComment: mut,
    useDeleteComment: mut,
  };
});

vi.mock("../src/features/hunts/api", () => ({
  useHunt: () => ({ data: { settings: { occupants: 1, cats: 0, dogs: 0 } } }),
}));

vi.mock("../src/features/rubric/api", () => ({
  useCatalog: () => ({ data: [{ key: "in_unit_laundry", label: "In-unit laundry" }] }),
}));

import { ListingDetailDrawer } from "../src/features/listings/ListingDetailDrawer";

function makeListing(): Listing {
  return {
    id: "l1",
    hunt_id: "h1",
    property_id: "prop1",
    added_by: "u1",
    status: "active",
    source_policy: "tiers_1_2_3",
    single_source_reason: null,
    pins: {},
    created_at: "2026-07-01T00:00:00Z",
    unavailable_at: null,
    all_in_components: null,
    property: {
      id: "prop1",
      name: "Maple Court",
      canonical_address: "1420 Alder St",
      city: null,
      state: null,
      county: null,
      official_url: null,
      floor_plans: [
        {
          id: "plan1",
          property_id: "prop1",
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
        hunt_listing_id: "l1",
        floor_plan_id: "plan1",
        total: 12,
        breakdown: {
          base: 10,
          total: 12,
          rubric_version: 1,
          clamped: false,
          gates: [],
          criteria: [{ key: "in_unit_laundry", value: "in_unit", matched: null, delta: 1 }],
        },
        rubric_version: 1,
        computed_at: "2026-07-10T00:00:00Z",
        all_in_components: {
          total: 1845,
          estimated_total: 210,
          components: [{ name: "base_rent", amount: 1600, tag: "actual" }],
          badges: [],
          mode: "conservative",
        },
      },
    ],
  };
}

function renderDrawer() {
  data.listings = [makeListing()];
  return render(
    <MantineProvider>
      <ListingDetailDrawer
        huntId="h1"
        selection={{ listingId: "l1", groupKey: "2-2" }}
        opened
        onClose={() => {}}
      />
    </MantineProvider>,
  );
}

describe("ListingDetailDrawer", () => {
  it("renders the hero and the five section cards for a scored listing", () => {
    renderDrawer();
    expect(screen.getByRole("heading", { name: "Maple Court" })).toBeInTheDocument();
    expect(screen.getByText("1420 Alder St")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Why this score/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Cost & fees/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Floor plans/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Notes & ratings/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Sources/ })).toBeInTheDocument();
  });
});
