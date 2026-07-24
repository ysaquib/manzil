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
    expect(screen.queryByText(/visible/)).not.toBeInTheDocument();
  });

  it("shows visible and filtered-out counts when filters are active", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, minScore: 5 },
      visibleCount: 12,
      totalCount: 19,
    });
    expect(screen.getByText("12 visible · 7 filtered out")).toBeInTheDocument();
  });

  it("shows zero visible when every row is filtered out", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, minRent: 9000 },
      visibleCount: 0,
      totalCount: 8,
    });
    expect(screen.getByText("0 visible · 8 filtered out")).toBeInTheDocument();
  });

  it("still exposes the filter controls while counts are shown", () => {
    renderBar({
      filters: { ...DEFAULT_OVERVIEW_FILTERS, cities: ["Ann Arbor"] },
      visibleCount: 3,
      totalCount: 10,
    });
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    expect(screen.getByLabelText("City")).toBeInTheDocument();
    expect(screen.getByText("3 visible · 7 filtered out")).toBeInTheDocument();
  });
});
