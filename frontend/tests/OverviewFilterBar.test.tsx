import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import { OverviewFilterBar } from "../src/features/listings/OverviewFilterBar";
import { DEFAULT_OVERVIEW_FILTERS } from "../src/features/listings/overviewRows";

function renderBar(
  props: Partial<Parameters<typeof OverviewFilterBar>[0]> = {},
) {
  const onChange = props.onChange ?? vi.fn();
  return renderWithProviders(
    <OverviewFilterBar
      filters={DEFAULT_OVERVIEW_FILTERS}
      onChange={onChange}
      cities={["Ann Arbor"]}
      visibleCount={12}
      totalCount={19}
      {...props}
    />,
  );
}

describe("OverviewFilterBar counts", () => {
  it("hides visible/filtered-out counts when no filters are active", () => {
    renderBar();
    expect(screen.queryByLabelText("Filter result summary")).not.toBeInTheDocument();
  });

  it("shows visible and filtered-out counts when filters are active", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, minScore: 5 },
      visibleCount: 12,
      totalCount: 19,
    });
    expect(screen.getByLabelText("Filter result summary")).toHaveTextContent(
      "12 visible · 7 filtered out",
    );
  });

  it("shows zero visible when every row is filtered out", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, minRent: 9000 },
      visibleCount: 0,
      totalCount: 8,
    });
    expect(screen.getByLabelText("Filter result summary")).toHaveTextContent(
      "0 visible · 8 filtered out",
    );
  });

  it("still exposes the filter controls while counts are shown", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, cities: ["Ann Arbor"] },
      visibleCount: 3,
      totalCount: 10,
    });
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    expect(screen.getByLabelText("City")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter result summary")).toHaveTextContent(
      "3 visible · 7 filtered out",
    );
  });

  it("calls out manual pins whose alternate Floor Plans may match", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, availableBy: "2026-08-15" },
      visibleCount: 4,
      totalCount: 10,
      manualPinAlternateMatchCount: 2,
    });
    expect(screen.getByLabelText("Manual pin filter note")).toHaveTextContent(
      "2 pinned Unit Groups may have another Floor Plan that meets these filters.",
    );
  });
});
