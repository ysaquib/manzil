import { fireEvent, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useAdminJobs = vi.hoisted(() => vi.fn());
const useAdminJob = vi.hoisted(() => vi.fn());
const useJobAction = vi.hoisted(() => vi.fn());
const useAdminDeleteJob = vi.hoisted(() => vi.fn());
const useReleaseLocks = vi.hoisted(() => vi.fn());
const mutate = vi.hoisted(() => vi.fn());

vi.mock("../src/features/admin/api", () => ({
  useAdminJobs,
  useAdminJob,
  useJobAction,
  useAdminDeleteJob,
  useReleaseLocks,
}));

import { AdminJobsPage } from "../src/features/admin/AdminJobsPage";

function renderPage() {
  return renderWithProviders(
    <MemoryRouter>
      <AdminJobsPage />
    </MemoryRouter>,
  );
}

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
  requested_by: null,
  requested_by_name: null,
  requested_by_email: null,
  stale: false,
};

const JOB_DETAIL = {
  ...FAILED_JOB,
  plan: { stages: ["FETCH", "EXTRACT"] },
  warnings: [{ stage: "FETCH", code: "partial", message: "One Source failed" }],
  requested_by: "user-1",
  requested_by_name: "Yusuf",
  requested_by_email: "yusuf@example.com",
  started_at: "2026-08-03T00:00:00Z",
  duration_seconds: 60,
  events: [
    { stage: "FETCH", event: "completed", detail: { tier: 3 }, at: "2026-08-03T00:00:20Z" },
  ],
  stage_costs: [
    {
      stage: "FETCH",
      llm_cost_usd: 0.002,
      fetch_cost_usd: 0.0015,
      llm_calls: 2,
      fetch_calls: 1,
      input_tokens: 101,
      output_tokens: 22,
      cache_read_tokens: 11,
      cache_write_tokens: 3,
      fetch_calls_by_provider: { brightdata: 1 },
      updated_at: "2026-08-03T00:00:20Z",
    },
  ],
};

describe("AdminJobsPage", () => {
  beforeEach(() => {
    mutate.mockReset();
    useAdminJobs.mockReturnValue({ data: [FAILED_JOB], isPending: false });
    useAdminJob.mockReturnValue({ data: JOB_DETAIL, isPending: false, error: null });
    useJobAction.mockReturnValue({ mutate, isPending: false });
    useAdminDeleteJob.mockReturnValue({ mutate: vi.fn(), isPending: false });
    useReleaseLocks.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: false,
    });
  });

  it("opens on all Jobs and retries through the AD-5 action", () => {
    renderPage();

    expect(useAdminJobs).toHaveBeenCalledWith({
      state: null,
      staleOnly: false,
      search: "",
      searchMode: "text",
    });
    expect(screen.getByText("Detroit Hunt")).toBeInTheDocument();
    expect(screen.getByText("Source blocked")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(mutate).toHaveBeenCalledWith({
      jobId: FAILED_JOB.id,
      action: "retry",
    });
  });

  it("opens a payload-safe detail drawer with timeline, plan, and complete costs", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Inspect Example Apartments" }));

    expect(await screen.findByRole("heading", { name: "Plan" })).toBeInTheDocument();
    expect(screen.getByText("One Source failed")).toBeInTheDocument();
    expect(screen.getByText("Yusuf")).toBeInTheDocument();
    expect(screen.getByText("FETCH · completed")).toBeInTheDocument();
    expect(screen.getByText("101 / 22")).toBeInTheDocument();
    expect(screen.getByText("brightdata: 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Job" })).toBeInTheDocument();
    expect(useAdminJob).toHaveBeenLastCalledWith(FAILED_JOB.id);
    expect(screen.getAllByRole("link", { name: "Detroit Hunt" })).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          href: expect.stringContaining(
            "/admin/hunts?search=hunt-1&search_mode=id&selected=hunt-1",
          ),
        }),
      ]),
    );
    expect(screen.getByRole("link", { name: "Yusuf" })).toHaveAttribute(
      "href",
      "/admin/people?search=user-1&search_mode=id&selected=user-1",
    );
  });
});
