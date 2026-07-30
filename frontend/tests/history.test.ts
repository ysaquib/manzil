import { describe, expect, it } from "vitest";

import {
  filterHistoryJobs,
  formatJobCostUsd,
  historySpendLabel,
  historySpendSummary,
  jobDuration,
} from "../src/features/jobs/history";

describe("jobDuration", () => {
  it("formats persisted wall-clock duration", () => {
    expect(
      jobDuration({
        created_at: "2026-07-11T00:00:00Z",
        finished_at: "2026-07-11T00:02:05Z",
      } as never),
    ).toBe("2m 5s");
  });

  it("returns null for unfinished jobs", () => {
    expect(jobDuration({ created_at: "2026-07-11T00:00:00Z" } as never)).toBeNull();
  });

  it("formats USD to four decimal places", () => {
    expect(formatJobCostUsd(0.0123)).toBe("$0.0123");
    expect(formatJobCostUsd(1)).toBe("$1.0000");
  });

  it("sums spend and run count", () => {
    const jobs = [
      { cost_actual_usd: 0.01 },
      { cost_actual_usd: 0.025 },
      { cost_actual_usd: null },
    ] as never;
    expect(historySpendSummary(jobs)).toEqual({ spendUsd: 0.035, runCount: 3 });
  });

  it("labels unfiltered total spend", () => {
    const jobs = [{ cost_actual_usd: 0.01 }, { cost_actual_usd: 0.02 }] as never;
    expect(historySpendLabel(jobs, jobs, false)).toBe("Total spend: $0.0300 · 2 runs");
  });

  it("labels filtered spend alongside the hunt total", () => {
    const all = [
      { cost_actual_usd: 0.01 },
      { cost_actual_usd: 0.02 },
      { cost_actual_usd: 0.03 },
    ] as never;
    const filtered = [all[0], all[2]] as never;
    expect(historySpendLabel(filtered, all, true)).toBe(
      "$0.0400 · 2 runs · $0.0600 total across 3 runs",
    );
  });

  it("composes listing, member, and outcome filters", () => {
    const jobs = [
      { id: "a", hunt_listing_id: "l1", state: "done" },
      { id: "b", hunt_listing_id: "l2", state: "failed" },
      { id: "c", hunt_listing_id: null, state: "done" },
    ] as never;
    expect(
      filterHistoryJobs(
        jobs,
        { listingId: "l2", memberId: "u2", outcome: "failed" },
        new Map([["l1", "u1"], ["l2", "u2"]]),
      ).map((job) => job.id),
    ).toEqual(["b"]);
  });
});
