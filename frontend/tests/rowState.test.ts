import { describe, expect, it } from "vitest";

import type { Job } from "../src/features/jobs/api";
import type { OverviewRow } from "../src/features/listings/overviewRows";
import { jobsByListing, rowPipelineState, formatPipelineError, pipelineFailureLabel, pipelineErrorWasTruncated } from "../src/features/listings/rowState";

const job = (over: Partial<Job> & { id: string }): Job =>
  ({
    hunt_listing_id: "L1",
    type: "ingest",
    state: "done",
    current_stage: null,
    attempts: 1,
    error: null,
    cost_actual_usd: 0,
    created_at: "2026-07-26T00:00:00Z",
    ...over,
  }) as Job;

const row = (over: Partial<OverviewRow> = {}): OverviewRow =>
  ({
    listing: { id: "L1" },
    group: { key: "2:1" },
    state: null,
    ...over,
  }) as OverviewRow;

describe("jobsByListing", () => {
  it("buckets by listing and puts the newest job first", () => {
    const map = jobsByListing([
      job({ id: "old", created_at: "2026-07-01T00:00:00Z" }),
      job({ id: "new", created_at: "2026-07-26T00:00:00Z" }),
      job({ id: "other", hunt_listing_id: "L2" }),
    ]);
    expect(map.get("L1")!.map((j) => j.id)).toEqual(["new", "old"]);
    expect(map.get("L2")!.map((j) => j.id)).toEqual(["other"]);
  });

  it("ignores jobs with no listing (hunt-wide rescores)", () => {
    const map = jobsByListing([job({ id: "x", hunt_listing_id: null })]);
    expect(map.size).toBe(0);
  });
});

describe("rowPipelineState", () => {
  it("is null when the listing has never had a job", () => {
    expect(rowPipelineState(row(), jobsByListing([]))).toBeNull();
  });

  it("is null when the last run simply finished", () => {
    expect(rowPipelineState(row(), jobsByListing([job({ id: "a", state: "done" })]))).toBeNull();
  });

  it.each(["queued", "running", "waiting_user"] as const)("reports %s as working", (state) => {
    const result = rowPipelineState(
      row(),
      jobsByListing([job({ id: "a", state, current_stage: "EXTRACT" })]),
    );
    expect(result).toMatchObject({ state: "working", detail: "EXTRACT", jobId: "a" });
  });

  it("reports a failed last run, carrying the error", () => {
    const result = rowPipelineState(
      row(),
      jobsByListing([job({ id: "a", state: "failed", error: "site blocked us" })]),
    );
    expect(result).toMatchObject({ state: "failed", detail: "site blocked us" });
  });

  it("lets an in-flight run outrank an earlier failure", () => {
    const result = rowPipelineState(
      row(),
      jobsByListing([
        job({ id: "old", state: "failed", created_at: "2026-07-01T00:00:00Z" }),
        job({ id: "new", state: "running", created_at: "2026-07-26T00:00:00Z" }),
      ]),
    );
    expect(result).toMatchObject({ state: "working", jobId: "new" });
  });

  it("marks a row with no scored group as a placeholder", () => {
    const result = rowPipelineState(
      row({ group: null }),
      jobsByListing([job({ id: "a", state: "running" })]),
    );
    expect(result!.placeholder).toBe(true);
  });

  it("does not blank a scored row that is merely refreshing", () => {
    // Losing the data you already have because a background refresh is running
    // would be a regression — the marker changes, the cells do not.
    const result = rowPipelineState(row(), jobsByListing([job({ id: "a", state: "running" })]));
    expect(result!.placeholder).toBe(false);
  });

  it("ignores jobs belonging to another listing", () => {
    const result = rowPipelineState(
      row(),
      jobsByListing([job({ id: "a", state: "running", hunt_listing_id: "L2" })]),
    );
    expect(result).toBeNull();
  });
});

describe("formatPipelineError", () => {
  it("collapses whitespace and leaves short messages intact", () => {
    expect(formatPipelineError("site blocked us")).toBe("site blocked us");
    expect(formatPipelineError("line one\nline two")).toBe("line one line two");
  });

  it("truncates long errors for Overview copy", () => {
    const long = "x".repeat(60);
    expect(formatPipelineError(long)).toHaveLength(48);
    expect(formatPipelineError(long).endsWith("…")).toBe(true);
    expect(pipelineErrorWasTruncated(long)).toBe(true);
  });

  it("builds the failure label", () => {
    expect(pipelineFailureLabel(null)).toBe("Couldn't fetch");
    expect(pipelineFailureLabel("timeout")).toBe("Couldn't fetch · timeout");
  });
});
