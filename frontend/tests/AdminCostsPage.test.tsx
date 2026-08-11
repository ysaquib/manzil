import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useCosts = vi.hoisted(() => vi.fn());
vi.mock("../src/features/admin/api", () => ({ useCosts }));

import { AdminCostsPage } from "../src/features/admin/AdminCostsPage";

describe("AdminCostsPage", () => {
  it("renders calendar labels and marks today's bucket as in progress", () => {
    const today = new Date();
    const label = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    useCosts.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        days: 7,
        timezone: "America/Detroit",
        total_cost_usd: 0.01,
        by_stage: [],
        by_hunt: [],
        by_model: [],
        grouped_by_current_pin: true,
        daily: [{ day: label, llm_cost_usd: 0.01, fetch_cost_usd: 0 }],
        tier3_credits_used: 0,
        tier3_credits_allowance: 5000,
      },
    });

    renderWithProviders(<AdminCostsPage />);

    expect(screen.getByText("Today · in progress")).toBeInTheDocument();
    expect(screen.getByTestId("today-cost-texture").getAttribute("style")).toContain(
      "repeating-linear-gradient",
    );
  });
});
