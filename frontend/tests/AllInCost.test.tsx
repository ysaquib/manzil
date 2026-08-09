import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import { AllInCell } from "../src/features/listings/AllInCost";
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
    expect(screen.getByLabelText("1 all-in warning")).toBeInTheDocument();
    expect(screen.queryByText("Fees unverified")).not.toBeInTheDocument(); // tooltip-only
  });

  it("keeps unknown heating as drawer provenance, not an Overview warning", () => {
    renderWithProviders(
      <AllInCell allIn={2055} composition={{ ...composition, badges: ["heat_unknown"] }} />,
    );
    expect(screen.queryByLabelText(/all-in warning/)).not.toBeInTheDocument();
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
