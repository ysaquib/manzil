import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import { AllInBreakdown, AllInCell } from "../src/features/listings/AllInCost";
import type { AllInComponents } from "../src/features/listings/types";

const composition: AllInComponents = {
  total: 2055.0,
  estimated_total: 210.0,
  components: [
    { name: "rent", amount: 1845, tag: "actual" },
    { name: "electric", amount: 120, tag: "estimated", note: "winter-weighted" },
    { name: "water", amount: 55, tag: "estimated" },
    { name: "trash", amount: 35, tag: "estimated" },
  ],
  badges: ["fees_unverified"],
  mode: "conservative",
};

describe("AllInCell", () => {
  it("renders the estimated portion visually distinct (§13.2)", () => {
    renderWithProviders(<AllInCell allIn={2055} composition={composition} />);
    expect(screen.getByText("$2,055")).toBeInTheDocument();
    expect(screen.getByText("(~$210 est.)")).toBeInTheDocument();
  });

  it("consolidates warnings into one icon, not a chip per badge", () => {
    renderWithProviders(
      <AllInCell
        allIn={2055}
        composition={{ ...composition, badges: ["fees_unverified", "heat_unknown"] }}
      />,
    );
    expect(screen.getByLabelText("2 all-in warnings")).toBeInTheDocument();
    expect(screen.queryByText("Fees unverified")).not.toBeInTheDocument(); // tooltip-only
  });

  it("shows no warning icon when the composition is clean", () => {
    renderWithProviders(
      <AllInCell allIn={2055} composition={{ ...composition, badges: [] }} />,
    );
    expect(screen.queryByLabelText(/all-in warning/)).not.toBeInTheDocument();
  });

  it("shows a dash with the warning icon when the total is unknown (§9.5 strict branch)", () => {
    renderWithProviders(
      <AllInCell allIn={null} composition={{ ...composition, total: null }} />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/est\.\)/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("1 all-in warning")).toBeInTheDocument();
  });
});

function renderBreakdown(comp: AllInComponents) {
  return renderWithProviders(<AllInBreakdown composition={comp} />);
}

describe("AllInBreakdown", () => {
  it("renders component rows with flush amounts and an all-in result box", () => {
    renderBreakdown({
      mode: "conservative",
      total: 1845,
      estimated_total: 210,
      overridden: false,
      badges: [],
      components: [
        { name: "base_rent", amount: 1635, tag: "actual", note: undefined },
        { name: "utilities", amount: 210, tag: "estimated", note: "gas heat" },
      ],
    });
    expect(screen.getByText("base rent")).toBeInTheDocument();
    expect(screen.getByText("$1,635")).toBeInTheDocument();
    expect(screen.getByText("All-in / mo")).toBeInTheDocument();
    expect(screen.getByText("$1,845")).toBeInTheDocument();
  });

  it("lists components with notes and the all-in result total", () => {
    renderWithProviders(<AllInBreakdown composition={composition} />);
    expect(screen.getByText("rent")).toBeInTheDocument();
    expect(screen.getByText("winter-weighted")).toBeInTheDocument();
    expect(screen.getAllByText("estimated")).toHaveLength(1);
    expect(screen.getByText("All-in / mo")).toBeInTheDocument();
    expect(screen.getByText("$2,055")).toBeInTheDocument();
    expect(screen.getByTitle("actual")).toHaveAttribute("data-state", "actual");
    expect(screen.getAllByTitle("estimated").some((el) => el.getAttribute("data-state") === "estimated")).toBe(true);
  });

  it("renders unknown components as unknown, never a number", () => {
    const withUnknown: AllInComponents = {
      ...composition,
      total: null,
      components: [
        ...composition.components,
        { name: "sewer", amount: null, tag: "unknown", note: "no baseline figure" },
      ],
    };
    renderWithProviders(<AllInBreakdown composition={withUnknown} />);
    expect(screen.getAllByText("unknown").length).toBeGreaterThanOrEqual(2); // component + total
  });
});
