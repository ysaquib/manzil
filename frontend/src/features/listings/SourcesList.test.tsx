import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../../../tests/testUtils";
import { SourcesList } from "./SourcesList";
import type { PropertySource, SingleSourceReason } from "./types";

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
}: {
  sources: PropertySource[];
  singleSourceReason?: SingleSourceReason | null;
}) {
  return renderWithProviders(
    <SourcesList
      sources={sources}
      sourcePolicy="tiers_1_2_3"
      huntId="hunt-1"
      listingId="listing-1"
      singleSourceReason={singleSourceReason}
      canEdit
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
});
