import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useAdminSummary = vi.hoisted(() => vi.fn());

vi.mock("../src/features/admin/api", () => ({ useAdminSummary }));

import { AdminOverviewPage } from "../src/features/admin/AdminOverviewPage";

const SUMMARY = {
  users: 4,
  hunts: 3,
  listings: 12,
  jobs_failed: 52,
  jobs_total: 80,
  spend_usd_30d: 1.25,
  tier3_credits_used: 4,
  tier3_credits_allowance: 5000,
  feedback_new: 0,
};

describe("AdminOverviewPage", () => {
  beforeEach(() => {
    useAdminSummary.mockReturnValue({
      data: SUMMARY,
      isPending: false,
      isError: false,
    });
  });

  it("sends failed Jobs to the landed AD-5 cross-Hunt queue", () => {
    renderWithProviders(
      <MemoryRouter>
        <AdminOverviewPage />
      </MemoryRouter>,
    );

    expect(screen.getByText("52 failed Jobs")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open the cross-hunt jobs queue/i }),
    ).toHaveAttribute("href", "/admin/jobs");
    expect(screen.queryByText(/arrives with AD-5/i)).not.toBeInTheDocument();
  });
});
