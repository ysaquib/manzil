import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import { SourcesList } from "../src/features/listings/SourcesList";
import type { PropertySource, RefreshStatus, SingleSourceReason } from "../src/features/listings/types";

const refreshMutate = vi.fn();

vi.mock("../src/features/listings/api", () => ({
  usePatchSourcePolicy: () => ({ mutate: vi.fn(), isPending: false }),
  useRefreshListing: () => ({ mutate: refreshMutate, isPending: false }),
  useRefreshStatuses: () => ({ data: [] as RefreshStatus[] }),
}));

function source(partial: Partial<PropertySource> & { id: string }): PropertySource {
  return {
    property_id: "prop-1",
    url: "https://example.com/x",
    site_domain: "example.com",
    is_official: false,
    last_fetched_at: null,
    last_success_at: null,
    ...partial,
  };
}

function renderSources({
  sources,
  singleSourceReason = null,
  jobs = [],
}: {
  sources: PropertySource[];
  singleSourceReason?: SingleSourceReason | null;
  jobs?: {
    hunt_listing_id: string | null;
    state: string;
    finished_at?: string | null;
    warnings?: { code: string; detail?: Record<string, unknown> }[];
  }[];
}) {
  return renderWithProviders(
    <SourcesList
      sources={sources}
      sourcePolicy="tiers_1_2_3"
      huntId="hunt-1"
      listingId="listing-1"
      singleSourceReason={singleSourceReason}
      canEdit
      jobs={jobs as never}
    />,
  );
}

describe("SourcesList", () => {
  it("renders compact source rows and only shows the reason with a single source", () => {
    renderSources({
      sources: [
        source({ id: "1", site_domain: "maplecourt.com", url: "https://maplecourt.com/x", is_official: true }),
        source({ id: "2", site_domain: "apartments.com", url: "https://apartments.com/y", is_official: false }),
      ],
      singleSourceReason: null,
    });
    expect(screen.getByText("maplecourt.com")).toBeInTheDocument();
    expect(screen.getByText("official")).toBeInTheDocument();
    expect(screen.queryByTestId("single-source")).not.toBeInTheDocument();
  });

  it("shows the single-source reason when only one source is present", () => {
    renderSources({
      sources: [source({ id: "1", site_domain: "maplecourt.com", is_official: true })],
      singleSourceReason: "trust_link",
    });
    expect(screen.getByTestId("single-source")).toBeInTheDocument();
  });

  it("renders the empty state when there are no sources", () => {
    renderSources({ sources: [] });
    expect(screen.getByText("No sources recorded yet.")).toBeInTheDocument();
  });

  it("shows Refresh images when the images marker is missing and queues images only", async () => {
    const user = userEvent.setup();
    renderSources({ sources: [source({ id: "1" })] });
    expect(screen.getByRole("button", { name: "Refresh images" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh images" }));
    expect(refreshMutate).toHaveBeenCalledWith(
      { listingId: "listing-1", fields: ["images"] },
      expect.any(Object),
    );
  });
});
