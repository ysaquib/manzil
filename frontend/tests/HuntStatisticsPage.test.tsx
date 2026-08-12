import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useHuntStatistics = vi.hoisted(() => vi.fn());
vi.mock("../src/features/statistics/api", () => ({ useHuntStatistics }));

import { HuntStatisticsPage } from "../src/features/statistics/HuntStatisticsPage";

describe("HuntStatisticsPage", () => {
  it("separates retained deleted spend and renders every operational series", () => {
    useHuntStatistics.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        days: 30,
        timezone: "America/Detroit",
        summary: {
          billed_cost_usd: 0.03,
          deleted_cost_usd: 0.02,
          listing_submissions: 2,
          jobs_completed: 1,
          jobs_failed: 1,
          llm_calls: 2,
          fetch_calls: 1,
        },
        daily: [
          {
            day: "2026-08-11",
            billed_cost_usd: 0.03,
            deleted_cost_usd: 0.02,
            listing_submissions: 2,
            jobs_completed: 1,
            jobs_failed: 1,
            llm_calls: 2,
            fetch_calls: 1,
          },
        ],
      },
    });

    renderWithProviders(<MemoryRouter><HuntStatisticsPage /></MemoryRouter>);

    expect(screen.getByText("Deleted Job spend")).toBeInTheDocument();
    expect(screen.getByText("$0.02")).toBeInTheDocument();
    expect(screen.getByText("Completion rate")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("Billed / completed Job")).toBeInTheDocument();
    expect(screen.getAllByText("$0.03")).toHaveLength(2);
    expect(screen.getAllByText("Listings submitted")).toHaveLength(2);
    expect(screen.getByText("Jobs by outcome")).toBeInTheDocument();
    expect(screen.getByText("Recorded calls")).toBeInTheDocument();
    expect(screen.getByText(/bucketed in America\/Detroit/)).toBeInTheDocument();
  });
});
