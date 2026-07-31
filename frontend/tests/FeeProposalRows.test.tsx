// Fee Proposal rows in Cost & fees (VC-7, DESIGN §9.7, §13.2).
//
// These rows are the single sanctioned exception to the one-icon action slot:
// accept and reject are both primary, and neither may hide behind a hover.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const decide = vi.fn();

vi.mock("../src/features/visits/api", () => ({
  useDecideFeeProposal: () => ({ mutate: decide, isPending: false }),
  useListingFeeProposals: () => ({ data: [], isLoading: false }),
}));

// CostAndFees reads the drawer's unsaved-edit context; this test is about the
// proposal rows, so the draft is simply empty.
vi.mock("../src/features/listings/ListingDetailDraft", () => ({
  useListingDetailDraft: () => ({
    draftOverrides: new Map(),
    setDraftOverride: vi.fn(),
    draftUtilities: new Map(),
    setDraftUtility: vi.fn(),
    draftFees: new Map(),
    setDraftFee: vi.fn(),
  }),
}));

import { CostAndFees, proposalLabel } from "../src/features/listings/CostAndFees";
import type { AllInComponents } from "../src/features/listings/types";
import type { VisitFeeProposal } from "../src/features/visits/types";
import { renderWithProviders } from "./testUtils";

const composition: AllInComponents = {
  total: 2310,
  estimated_total: 0,
  mode: "conservative",
  badges: [],
  components: [{ name: "rent", amount: 2100, tag: "actual" }],
};

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
    created_by: "u2",
    created_at: "2026-07-30T10:00:00Z",
    ...partial,
  };
}

function render(proposals: VisitFeeProposal[], canDecide = true) {
  return renderWithProviders(
    <CostAndFees
      composition={composition}
      fees={[]}
      huntId="h1"
      proposals={proposals}
      canDecideProposals={canDecide}
      memberNames={new Map([["u2", "Sana"]])}
    />,
  );
}

beforeEach(() => decide.mockReset());

describe("proposalLabel", () => {
  it("names an override target in the section's own vocabulary", () => {
    expect(proposalLabel(proposal({ target: "override", target_key: "base_rent" }))).toBe(
      "Base rent",
    );
    expect(proposalLabel(proposal({ target: "override", target_key: "all_in_monthly" }))).toBe(
      "All-in monthly",
    );
  });

  it("uses the fee slot's own label", () => {
    expect(proposalLabel(proposal({ target_key: "pet_deposit" }))).toBe("Pet deposit");
  });

  it("degrades readably for a slot it does not know", () => {
    expect(proposalLabel(proposal({ target_key: "some_new_fee" }))).toBe("some new fee");
  });
});

describe("Fee Proposal rows", () => {
  it("shows nothing when no figure has been offered — the usual case", () => {
    render([]);
    expect(screen.queryByText("Confirmed on a visit")).not.toBeInTheDocument();
  });

  it("renders the offer with its amount and who confirmed it", () => {
    render([proposal()]);
    expect(screen.getByText("Confirmed on a visit")).toBeInTheDocument();
    // "Parking" is also an ordinary fee slot row, so the proposal is identified
    // by its own dot and subline rather than by the label alone.
    const row = document.querySelector('[data-testid="proposal-parking"]')!.closest("div")!;
    expect(within(row.parentElement!).getByText("Parking")).toBeInTheDocument();
    expect(screen.getByText("$85")).toBeInTheDocument();
    expect(screen.getByText(/Sana confirmed this on a tour/)).toBeInTheDocument();
  });

  it("marks the row as pending, so it reads as staged rather than settled", () => {
    // The same presentation an unsaved manual edit uses — because that is what
    // a proposal is.
    render([proposal()]);
    const dot = document.querySelector('[data-testid="proposal-parking"]');
    expect(dot).toHaveAttribute("data-state", "pending");
  });

  it("offers accept and reject together, neither behind a hover", () => {
    render([proposal()]);
    expect(screen.getByRole("button", { name: "accept Parking" })).toBeVisible();
    expect(screen.getByRole("button", { name: "reject Parking" })).toBeVisible();
  });

  it("accepts, carrying the Visit the offer came from", async () => {
    render([proposal()]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "accept Parking" }));
    expect(decide).toHaveBeenCalledWith({
      visitId: "v1",
      proposalId: "fp1",
      action: "accept",
    });
  });

  it("rejects through the same path — the Visit keeps its own figure", async () => {
    render([proposal()]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "reject Parking" }));
    expect(decide).toHaveBeenCalledWith({
      visitId: "v1",
      proposalId: "fp1",
      action: "reject",
    });
  });

  it("shows the offer but no decision controls to someone who cannot write cost", () => {
    // Deciding is a cost write (§4.2). Seeing that a figure was confirmed is
    // still useful to everyone else.
    render([proposal()], false);
    expect(screen.getByText(/Sana confirmed this on a tour/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "accept Parking" })).not.toBeInTheDocument();
  });

  it("lists several offers from one tour", () => {
    render([
      proposal(),
      proposal({ id: "fp2", target: "override", target_key: "base_rent", amount: 2150 }),
    ]);
    expect(screen.getByRole("button", { name: "accept Parking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "accept Base rent" })).toBeInTheDocument();
  });

  it("keeps offers from different tours separately decidable", async () => {
    render([proposal(), proposal({ id: "fp2", visit_id: "v2", target_key: "admin" })]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "accept Admin fee" }));
    expect(decide).toHaveBeenCalledWith({
      visitId: "v2",
      proposalId: "fp2",
      action: "accept",
    });
  });
});
