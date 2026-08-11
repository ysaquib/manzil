import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useAdminJobs = vi.hoisted(() => vi.fn());
const useJobAction = vi.hoisted(() => vi.fn());
const useAdminDeleteJob = vi.hoisted(() => vi.fn());
const useReleaseLocks = vi.hoisted(() => vi.fn());
const mutate = vi.hoisted(() => vi.fn());

vi.mock("../src/features/admin/api", () => ({
  useAdminJobs,
  useJobAction,
  useAdminDeleteJob,
  useReleaseLocks,
}));

import { AdminJobsPage } from "../src/features/admin/AdminJobsPage";

const FAILED_JOB = {
  id: "00000000-0000-0000-0000-000000000052",
  hunt_id: "hunt-1",
  hunt_name: "Detroit Hunt",
  listing_name: "Example Apartments",
  type: "ingest",
  state: "failed",
  current_stage: "EXTRACT",
  attempts: 3,
  error: "Source blocked",
  cost_actual_usd: 0.0123,
  created_at: "2026-08-03T00:00:00Z",
  finished_at: "2026-08-03T00:01:00Z",
  locked_by: null,
  locked_at: null,
  stale: false,
};

describe("AdminJobsPage", () => {
  beforeEach(() => {
    mutate.mockReset();
    useAdminJobs.mockReturnValue({ data: [FAILED_JOB], isPending: false });
    useJobAction.mockReturnValue({ mutate, isPending: false });
    useAdminDeleteJob.mockReturnValue({ mutate: vi.fn(), isPending: false });
    useReleaseLocks.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: false,
    });
  });

  it("opens on failed Jobs and retries through the AD-5 action", () => {
    renderWithProviders(<AdminJobsPage />);

    expect(useAdminJobs).toHaveBeenCalledWith("failed", false);
    expect(screen.getByText("Detroit Hunt")).toBeInTheDocument();
    expect(screen.getByText("Source blocked")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(mutate).toHaveBeenCalledWith({
      jobId: FAILED_JOB.id,
      action: "retry",
    });
  });
});
