import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Listing } from "../src/features/listings/types";

const data = vi.hoisted(() => ({
  listings: [] as unknown[],
  extractions: [] as unknown[],
}));

vi.mock("../src/auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: "u1" } } }),
}));

vi.mock("../src/features/listings/api", () => {
  const mut = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  return {
    useListings: () => ({ data: data.listings, isLoading: false, error: null }),
    useFees: () => ({ data: [] }),
    useExtractions: () => ({ data: data.extractions, isLoading: false }),
    useOverrides: () => ({ data: [] }),
    useUtilityOverrides: () => ({ data: [] }),
    usePropertyImages: () => ({ data: [], isLoading: false }),
    usePropertyContacts: () => ({ data: [] }),
    useResolutionCandidates: () => ({ data: [] }),
    usePatchPins: mut,
    useCreateOverride: mut,
    useUpsertFee: mut,
    useUpsertUtilityOverride: mut,
    usePatchSourcePolicy: mut,
    useRefreshListing: mut,
    useRefreshStatuses: () => ({ data: [] }),
    useRefreshStalls: () => ({ data: [] }),
  };
});

vi.mock("../src/features/collaboration/api", () => {
  const mut = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  return {
    useMembers: () => ({ data: [] }),
    useHuntContributors: () => ({ data: [], isLoading: false }),
    useCurrentMember: () => ({ data: { user_id: "u1", role: "owner", color: "moss" } }),
    useComments: () => ({ data: [] }),
    useRatings: () => ({ data: [] }),
    useSetRating: mut,
    useCreateComment: mut,
    useUpdateComment: mut,
    useDeleteComment: mut,
  };
});

// The Cost & fees card now reads Fee Proposals (VC-7); this test isolates data
// hooks by module, and an unmocked useQuery has no client here.
vi.mock("../src/features/visits/api", () => ({
  useListingFeeProposals: () => ({ data: [], isLoading: false }),
  useDecideFeeProposal: () => ({ mutate: vi.fn(), isPending: false }),
  // The Visits section (VC-8).
  usePropertyVisits: () => ({ data: [], isLoading: false }),
  useVisitUnitGroupScores: () => ({ data: [], isLoading: false }),
  visitScoreKey: (listingId: string, groupKey: string | null) => `${listingId}:${groupKey ?? ""}`,
}));

vi.mock("../src/features/hunts/api", () => ({
  useHunt: () => ({ data: { settings: { occupants: 1, cats: 0, dogs: 0 } } }),
}));

vi.mock("../src/features/rubric/api", () => ({
  useResolvedCatalog: () => ({
    data: [{ key: "in_unit_laundry", label: "In-unit laundry", category: "unit", domain: "rent", fact_scope: "mixed", value_schema: { type: "string" }, default_options: [], extraction_hint: "", requires_tool: null, refresh_class: "listing_details" }],
  }),
  // This hunt has no manual Criteria, so the "Your answers" section stays away.
  useRubric: () => ({ data: [] }),
}));

import { ListingDetailDrawer } from "../src/features/listings/ListingDetailDrawer";

function renderWithProviders(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>,
  );
}

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
      lat: null,
      lng: null,
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
  data.extractions = [];
  return renderWithProviders(
    <ListingDetailDrawer
      huntId="h1"
      selection={{ listingId: "l1", groupKey: "2-2" }}
      opened
      onClose={() => {}}
    />,
  );
}

it("shows Problematic when reconciliation used a conservative disputed fallback", () => {
  data.listings = [makeListing()];
  data.extractions = [
    {
      id: "resolved-1",
      disputed: true,
      resolution_rule: "conservative_disputed",
    },
  ];
  renderWithProviders(
    <ListingDetailDrawer
      huntId="h1"
      selection={{ listingId: "l1", groupKey: "2-2" }}
      opened
      onClose={() => {}}
    />,
  );

  expect(screen.getByLabelText("Problematic")).toBeInTheDocument();
  expect(screen.getByLabelText("Problematic").parentElement).toHaveStyle({
    color: "var(--mantine-color-dimmed)",
  });
});

describe("ListingDetailDrawer", () => {
  it("renders the hero and one consolidated cost & fees card for a scored listing", () => {
    renderDrawer();
    expect(screen.getByRole("heading", { name: "Maple Court" })).toBeInTheDocument();
    expect(screen.getByText("1420 Alder St")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Why this score/ })).toBeInTheDocument();
    // §9.5 consolidation: one section, not the old Cost Breakdown / Fees split.
    expect(screen.getByRole("heading", { name: /Cost & fees/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Cost Breakdown/ })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Floor plans/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Notes & ratings/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Location/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Sources/ })).toBeInTheDocument();
  });

  // The fixture property has no geocode and no browser Maps key in the test
  // env — the Location card must still render its address-only fallback
  // rather than an error (§12: coordinates arrive with a run, not at submit).
  it("falls back to an address-only location card without coordinates", () => {
    renderDrawer();
    expect(screen.getByText("Address only")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open in Maps/ })).toHaveAttribute(
      "href",
      expect.stringContaining("1420%20Alder%20St"),
    );
  });
});
