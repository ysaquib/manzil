import { describe, expect, it } from "vitest";

import { filterHistoryJobs, jobDuration } from "./history";

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
