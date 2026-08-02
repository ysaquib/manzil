// §9.5 consolidation + P3-SC8: the drawer's single Cost & fees section.
// These assert the encodings the design is explicit about — an uncounted charge
// is dimmed and struck rather than chipped, a human's figure underlines itself,
// pending never looks like saved, refundability rides as an icon, and an
// incomplete move-in ledger is never presented as a total.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import { CostAndFees } from "../src/features/listings/CostAndFees";
import { ListingDetailDraftProvider } from "../src/features/listings/ListingDetailDraft";
import type { HuntMember } from "../src/features/collaboration/api";
import type {
  AllInComponents,
  FeeEntry,
  Listing,
  MoveInComponents,
  UtilityOverride,
} from "../src/features/listings/types";

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

const composition: AllInComponents = {
  total: 2146,
  estimated_total: 261,
  mode: "conservative",
  badges: [],
  components: [
    { name: "rent", amount: 1795, tag: "actual" },
    { name: "electric", amount: 148, tag: "estimated", note: "Wayne County, MI regional estimate" },
    { name: "gas", amount: 113, tag: "estimated" },
  ],
};

const moveIn: MoveInComponents = {
  total: 2670,
  subtotal: 2670,
  refundable_total: 500,
  non_refundable_total: 2170,
  unclassified_total: 0,
  incomplete: false,
  badges: [],
  charges: [
    {
      name: "first_month",
      amount: 1795,
      tag: "actual",
      required: true,
      refundable: false,
      counted: true,
      note: "base rent — one full month, no prorated schedule stated",
    },
    {
      name: "security_deposit",
      amount: 500,
      tag: "actual",
      required: true,
      refundable: true,
      counted: true,
    },
    {
      name: "application_fee",
      amount: 375,
      tag: "actual",
      required: true,
      refundable: false,
      counted: true,
    },
  ],
};

const parkingFee: FeeEntry = {
  hunt_listing_id: "listing-1",
  fee_slot: "parking",
  amount: 50,
  value_state: "extracted",
  entered_by: null,
  evidence_ref: null,
  updated_at: null,
};

function render(
  fees: FeeEntry[],
  extra?: {
    composition?: AllInComponents | null;
    moveIn?: MoveInComponents | null;
    members?: HuntMember[];
    utilityOverrides?: UtilityOverride[];
    extractedIncluded?: string[];
    household?: { occupants: number; cats: number; dogs: number };
    feeOriginals?: Map<string, number>;
  },
) {
  return renderWithProviders(
    <ListingDetailDraftProvider
      huntId="hunt-1"
      listing={listingFixture}
      serverFees={fees}
      serverUtilityOverrides={extra?.utilityOverrides}
    >
      <CostAndFees
        composition={extra?.composition === undefined ? composition : extra.composition}
        moveIn={extra?.moveIn === undefined ? moveIn : extra.moveIn}
        fees={fees}
        members={extra?.members}
        utilityOverrides={extra?.utilityOverrides}
        extractedIncluded={extra?.extractedIncluded}
        household={extra?.household ?? { occupants: 2, cats: 0, dogs: 0 }}
        feeOriginals={extra?.feeOriginals}
      />
    </ListingDetailDraftProvider>,
  );
}

function rowFor(label: string): HTMLElement {
  const node = screen.getByText(label).closest("[data-counted]");
  if (!node) throw new Error(`no cost row for ${label}`);
  return node as HTMLElement;
}

describe("CostAndFees", () => {
  it("shows one section with both totals rather than two competing ledgers", () => {
    render([parkingFee]);
    expect(screen.getAllByText("All-in / month").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Cash at move-in").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$2,146").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$2,670").length).toBeGreaterThan(0);
  });

  it("renders base rent as its own overrideable row", async () => {
    const user = userEvent.setup();
    render([]);
    expect(within(rowFor("Base rent")).getByText("$1,795")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "edit Base rent" }));
    expect(await screen.findByRole("textbox", { name: "Note" })).toBeInTheDocument();
  });

  it("dims and strikes an uncounted charge instead of chipping it", () => {
    render([{ ...parkingFee, fee_slot: "pet_rent", amount: 35 }], {
      household: { occupants: 2, cats: 0, dogs: 0 },
    });
    const row = rowFor("Pet rent");
    expect(row).toHaveAttribute("data-counted", "no");
    expect(within(row).getByText("$35")).toHaveAttribute("data-struck", "true");
    expect(within(row).getByText(/no pets in this hunt's household/i)).toBeInTheDocument();
    expect(screen.queryByText("not counted")).not.toBeInTheDocument();
  });

  it("underlines a human's figure rather than labelling it 'manual'", () => {
    render([{ ...parkingFee, value_state: "manual", entered_by: "uuid-yusuf" }], {
      members: [
        {
          hunt_id: "hunt-1",
          user_id: "uuid-yusuf",
          role: "owner",
          color: "moss",
          display_name: "Yusuf",
        },
      ],
    });
    const row = rowFor("Parking");
    expect(within(row).getByText("$50")).toHaveAttribute("data-manual", "true");
    expect(within(row).getByText(/Yusuf entered this/)).toBeInTheDocument();
    expect(within(row).queryByText("manual")).not.toBeInTheDocument();
    // A revert must be reachable without hovering first.
    expect(within(row).getByRole("button", { name: /revert Parking/i })).toBeInTheDocument();
  });

  it("marks a pending edit as provisional, distinct from a saved override", async () => {
    const user = userEvent.setup();
    render([parkingFee]);
    await user.click(screen.getByRole("button", { name: "edit Parking" }));
    const amount = await screen.findByRole("textbox", { name: "Monthly amount" });
    await user.clear(amount);
    await user.type(amount, "75");
    await user.click(await screen.findByRole("button", { name: "Apply" }));

    const row = rowFor("Parking");
    expect(row).toHaveAttribute("data-pending", "true");
    expect(screen.getByTestId("fee-state-parking")).toHaveAttribute("data-state", "pending");
    expect(within(row).getByText(/applies when you save/i)).toBeInTheDocument();
  });

  it("shows inclusion as a quiet icon and keeps the utility editable", async () => {
    const user = userEvent.setup();
    render([], { extractedIncluded: ["water"] });
    const row = rowFor("Water");
    expect(within(row).getByLabelText("included in rent")).toBeInTheDocument();
    expect(row).toHaveAttribute("data-counted", "no");

    await user.click(screen.getByRole("button", { name: "edit Electricity" }));
    const included = await screen.findByRole("checkbox", { name: "Included in rent" });
    expect(included).not.toBeChecked();
    await user.click(included);
    await user.click(await screen.findByRole("button", { name: "Apply" }));
    expect(screen.getByTestId("utility-state-electric")).toHaveAttribute("data-state", "pending");
  });

  it("summarises included utilities on the group header with its inclusion level", () => {
    render([], { extractedIncluded: ["trash", "electric"] });
    const summary = screen.getByText(/included: electric · trash/);
    expect(summary).toHaveAttribute("data-level", "highest");
  });

  it("uses the minor-inclusion level when no major utility is included", () => {
    render([], { extractedIncluded: ["trash", "sewer"] });
    expect(screen.getByText(/included: sewer · trash/)).toHaveAttribute("data-level", "high");
  });

  it("shows refundability as icons, never as chips", () => {
    render([]);
    expect(within(rowFor("Security deposit")).getByLabelText("refundable")).toBeInTheDocument();
    expect(within(rowFor("First month")).getByLabelText("non-refundable")).toBeInTheDocument();
    expect(screen.queryByText("refundable", { selector: ".mantine-Badge-root" })).toBeNull();
  });

  it("reserves the action column on read-only rows so amounts align with editable ones", () => {
    render([]);
    const firstMonthAmount = within(rowFor("First month")).getByText(/\$/);
    const valueAction = firstMonthAmount.parentElement;
    expect(valueAction?.childElementCount).toBe(2);
    expect(valueAction?.lastElementChild).toHaveAttribute("aria-hidden", "true");
    expect(valueAction?.lastElementChild?.tagName).toBe("BUTTON");
    expect(
      within(rowFor("Security deposit")).getByRole("button", { name: "edit Security deposit" }),
    ).toBeInTheDocument();
    expect(
      within(rowFor("Application fee")).getByRole("button", { name: "edit Application fee" }),
    ).toBeInTheDocument();
  });

  it("allows editing an unmapped mandatory fee that composes into all-in", async () => {
    const user = userEvent.setup();
    const withAmenity: AllInComponents = {
      ...composition,
      total: 2156,
      components: [
        ...composition.components,
        { name: "amenity fee", amount: 10, tag: "actual" },
      ],
    };
    render([], {
      composition: withAmenity,
      feeOriginals: new Map([["amenity fee", 10]]),
    });
    await user.click(screen.getByRole("button", { name: "edit amenity fee" }));
    const amountInput = await screen.findByRole("textbox", { name: "Monthly amount" });
    await user.clear(amountInput);
    await user.type(amountInput, "15");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByTestId("fee-state-amenity fee")).toHaveAttribute("data-state", "pending");
  });

  it("presents an incomplete move-in cost as a subtotal, never as a total", () => {
    render([], {
      moveIn: {
        ...moveIn,
        total: null,
        subtotal: 2646,
        incomplete: true,
        badges: ["move_in_incomplete"],
      },
    });
    expect(screen.getAllByText("$2,646+").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Incomplete").length).toBeGreaterThan(0);
    expect(screen.getByText(/known subtotal — not a total/i)).toBeInTheDocument();
  });

  it("splits refundable from non-refundable under the move-in total", () => {
    render([]);
    expect(screen.getByText("Refundable").parentElement).toHaveTextContent("$500");
    expect(screen.getByText("Non-refundable").parentElement).toHaveTextContent("$2,170");
  });

  it("offers required / refundable / credited decisions on a one-time charge", async () => {
    const user = userEvent.setup();
    render([]);
    await user.click(screen.getByRole("button", { name: "edit Application fee" }));
    expect(await screen.findByRole("checkbox", { name: "Required to move in" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Refundable" })).toBeInTheDocument();
    const credited = screen.getByRole("checkbox", {
      name: "Credited to first month's rent",
    });
    expect(credited).not.toBeChecked();
    await user.click(credited);
    expect(
      await screen.findByRole("textbox", { name: "Credited amount" }),
    ).toBeInTheDocument();
  });

  it("says so plainly when nothing has been composed yet", () => {
    render([], { composition: null, moveIn: null });
    expect(screen.getByText(/ingestion may still be running/i)).toBeInTheDocument();
  });
});
