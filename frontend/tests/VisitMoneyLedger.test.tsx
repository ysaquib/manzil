// The money ledger (VC-7).
//
// The rule under test throughout: this offers figures, it never writes them.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createProposal = vi.fn();
const withdrawProposal = vi.fn();

vi.mock("../src/features/visits/api", () => ({
  useCreateFeeProposal: () => ({ mutate: createProposal, isPending: false }),
  useWithdrawFeeProposal: () => ({ mutate: withdrawProposal, isPending: false }),
}));

import {
  LEDGER_LINES,
  VisitMoneyLedger,
  formatMoney,
  listingFigure,
} from "../src/features/visits/VisitMoneyLedger";
import type { AllInComponents, Listing } from "../src/features/listings/types";
import type { VisitFeeProposal, VisitUnit } from "../src/features/visits/types";
import { renderWithProviders } from "./testUtils";

const composition: AllInComponents = {
  total: 2310,
  estimated_total: 60,
  mode: "conservative",
  badges: [],
  components: [
    { name: "rent", amount: 2100, tag: "actual" },
    { name: "parking", amount: 60, tag: "estimated" },
  ],
};

const listing = {
  id: "hl1",
  property_id: "p1",
  all_in_components: composition,
} as unknown as Listing;

const unit = { id: "un1", label: "4B" } as unknown as VisitUnit;

function proposal(partial: Partial<VisitFeeProposal> = {}): VisitFeeProposal {
  return {
    id: "fp1",
    visit_id: "v1",
    visit_unit_id: "un1",
    hunt_listing_id: "hl1",
    target: "fee_slot",
    target_key: "parking",
    amount: 85,
    note: null,
    status: "pending",
    decided_by: null,
    decided_at: null,
    created_by: "me",
    created_at: "2026-07-30T10:00:00Z",
    ...partial,
  };
}

function render(props: Partial<Parameters<typeof VisitMoneyLedger>[0]> = {}) {
  return renderWithProviders(
    <VisitMoneyLedger
      visitId="v1"
      listing={listing}
      proposals={[]}
      activeUnit={unit}
      {...props}
    />,
  );
}

beforeEach(() => {
  createProposal.mockReset();
  withdrawProposal.mockReset();
});

describe("listingFigure", () => {
  const line = (key: string) => LEDGER_LINES.find((l) => l.targetKey === key)!;

  it("reads base rent from the composer's own 'rent' component", () => {
    // Matched exactly, not by substring: "pet rent" also contains "rent".
    expect(listingFigure(line("base_rent"), composition).amount).toBe(2100);
  });

  it("reads the all-in total from the composition total", () => {
    expect(listingFigure(line("all_in_monthly"), composition).amount).toBe(2310);
  });

  it("matches a fee component loosely, because those names come off a page", () => {
    const parking = listingFigure(line("parking"), composition);
    expect(parking.amount).toBe(60);
    expect(parking.tag).toBe("estimated");
  });

  it("says nothing rather than guessing when the listing has no such line", () => {
    expect(listingFigure(line("admin"), composition).amount).toBeNull();
  });

  it("survives a listing with no composition at all", () => {
    expect(listingFigure(line("base_rent"), null).amount).toBeNull();
  });
});

describe("formatMoney", () => {
  it("renders an em dash for an unknown figure rather than $0", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(2100)).toBe("$2,100");
  });
});

describe("VisitMoneyLedger", () => {
  it("shows what the listing currently believes, beside the offer control", () => {
    render();
    expect(screen.getByText("Base rent")).toBeInTheDocument();
    expect(screen.getByText(/Listing says \$2,100/)).toBeInTheDocument();
  });

  it("says plainly that these are offers, not edits", () => {
    render();
    expect(screen.getByText(/Nothing on the listing changes until someone accepts/)).toBeInTheDocument();
  });

  it("renders nothing when the visited Property has no Listing to offer to", () => {
    render({ listing: undefined });
    expect(screen.queryByText("Base rent")).not.toBeInTheDocument();
  });

  it("offers a typed figure to the listing", async () => {
    render();
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /Base rent confirmed on the tour/ }), "2150");
    await user.click(screen.getByRole("button", { name: "Propose Base rent" }));

    expect(createProposal).toHaveBeenCalledWith(
      expect.objectContaining({
        hunt_listing_id: "hl1",
        target: "override",
        target_key: "base_rent",
        amount: 2150,
      }),
    );
  });

  it("will not offer an empty figure", () => {
    render();
    expect(screen.getByRole("button", { name: "Propose Base rent" })).toBeDisabled();
  });

  it("files a monthly charge against the unit that was walked", async () => {
    render();
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /Pet rent confirmed/ }), "40");
    await user.click(screen.getByRole("button", { name: "Propose Pet rent" }));
    expect(createProposal).toHaveBeenCalledWith(
      expect.objectContaining({ target_key: "pet_rent", visit_unit_id: "un1" }),
    );
  });

  it("files an application fee against the building, not a door", async () => {
    // One application fee covers the property; attaching it to a unit would
    // imply the next unit has its own.
    render();
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /Application fee confirmed/ }), "50");
    await user.click(screen.getByRole("button", { name: "Propose Application fee" }));
    expect(createProposal).toHaveBeenCalledWith(
      expect.objectContaining({ target_key: "application_fee", visit_unit_id: null }),
    );
  });

  it("shows a standing offer instead of the input, and counts it", () => {
    render({ proposals: [proposal()] });
    expect(screen.getByText("Offered $85")).toBeInTheDocument();
    expect(screen.getByText("1 figure offered")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Parking confirmed/ })).not.toBeInTheDocument();
  });

  it("lets the offer be withdrawn before anyone decides", async () => {
    render({ proposals: [proposal()] });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Withdraw Parking offer" }));
    expect(withdrawProposal).toHaveBeenCalledWith("fp1");
  });

  it("ignores a decided proposal — the row is free to be offered again", () => {
    render({ proposals: [proposal({ status: "rejected" })] });
    expect(screen.queryByText("Offered $85")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Parking confirmed/ })).toBeInTheDocument();
  });

  it("offers nothing on a finished visit", () => {
    render({ readOnly: true });
    expect(screen.getByRole("button", { name: "Propose Base rent" })).toBeDisabled();
  });
});
