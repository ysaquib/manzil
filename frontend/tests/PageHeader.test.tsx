import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "./testUtils";
import { PageHeader } from "../src/components/PageHeader";

describe("PageHeader", () => {
  it("renders title, description, and right slot", () => {
    renderWithProviders(
      <PageHeader
        title="Overview"
        description="All unit groups"
        rightSlot={<button type="button">Filter</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText("All unit groups")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Filter" })).toBeInTheDocument();
  });
});
