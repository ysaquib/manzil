import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PermanentDeleteListingModal } from "../src/features/listings/PermanentDeleteListingModal";
import { renderWithProviders } from "./testUtils";

const mocks = vi.hoisted(() => ({
  activeJobs: 0,
  mutate: vi.fn(),
}));

vi.mock("../src/features/listings/api", () => ({
  useListingDeletionImpact: () => ({
    data: {
      listing_id: "listing-1",
      property_id: "property-1",
      property_name: "The Grove",
      status: "archived",
      active_jobs: mocks.activeJobs,
      counts: {
        unit_groups: 3,
        scores: 4,
        manual_values: 5,
        collaboration_records: 6,
        task_records: 7,
        visits: 2,
        visit_records: 8,
        hunt_scoped_extractions: 1,
      },
    },
    isLoading: false,
    error: null,
  }),
  usePermanentDeleteListing: () => ({
    isPending: false,
    mutate: mocks.mutate,
  }),
}));

describe("PermanentDeleteListingModal", () => {
  beforeEach(() => {
    mocks.activeJobs = 0;
    mocks.mutate.mockReset();
  });

  it("requires the exact Property name and submits it as confirmation", () => {
    renderWithProviders(
      <PermanentDeleteListingModal
        huntId="hunt-1"
        target={{ id: "listing-1", propertyName: "The Grove" }}
        onClose={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: "Permanently delete", hidden: true });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Type “The Grove” to confirm", { selector: "input" }), {
      target: { value: "the grove" },
    });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Type “The Grove” to confirm", { selector: "input" }), {
      target: { value: "The Grove" },
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(mocks.mutate).toHaveBeenCalledWith(
      { listingId: "listing-1", confirmationName: "The Grove" },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
    );
  });

  it("blocks deletion while a Job is active", () => {
    mocks.activeJobs = 2;
    renderWithProviders(
      <PermanentDeleteListingModal
        huntId="hunt-1"
        target={{ id: "listing-1", propertyName: "The Grove" }}
        onClose={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Type “The Grove” to confirm", { selector: "input" }), {
      target: { value: "The Grove" },
    });
    expect(screen.getByText(/2 queued, running, or waiting Jobs/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Permanently delete", hidden: true })).toBeDisabled();
  });
});
