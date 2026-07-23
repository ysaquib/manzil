import { describe, expect, it } from "vitest";

import type { Job } from "./api";
import { PHASE_ORDER, phasesForJob } from "./pipelinePhases";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    hunt_listing_id: "listing-1",
    type: "ingest",
    state: "running",
    current_stage: "EXTRACT",
    attempts: 1,
    error: null,
    cost_actual_usd: 0,
    ...overrides,
  };
}

const fullPlan = {
  stages: [
    "PLAN",
    "VALIDATE_URL",
    "FETCH",
    "VALIDATE",
    "EXTRACT",
    "DEDUPE",
    "DISCOVER",
    "IMAGE_FETCH",
    "VISION",
    "VERIFY",
    "ENRICH",
    "SCORE",
  ],
};

function statusOf(job: Job, key: string) {
  const model = phasesForJob(job);
  const phase = model.phases.find((p) => p.key === key);
  if (!phase) throw new Error(`no phase ${key}`);
  return phase;
}

describe("phasesForJob", () => {
  it("always renders the five canonical phases in order", () => {
    const model = phasesForJob(job({ plan: fullPlan }));
    expect(model.phases.map((p) => p.key)).toEqual(PHASE_ORDER);
  });

  it("marks passed phases done, the current phase active, and later phases pending", () => {
    const j = job({ plan: fullPlan, current_stage: "EXTRACT", state: "running" });
    expect(statusOf(j, "prepare").status).toBe("done");
    expect(statusOf(j, "fetch").status).toBe("done");
    const read = statusOf(j, "read");
    expect(read.status).toBe("active");
    expect(read.tone).toBe("running");
    expect(statusOf(j, "verify").status).toBe("pending");
    expect(statusOf(j, "score").status).toBe("pending");
    expect(phasesForJob(j).caption).toBe("Reading the listing…");
    expect(phasesForJob(j).stageToken).toBe("EXTRACT");
  });

  it("reports the active phase's sub-steps: total stages and current index", () => {
    // Read covers EXTRACT · DEDUPE · DISCOVER · IMAGE_FETCH · VISION.
    expect(phasesForJob(job({ plan: fullPlan, current_stage: "EXTRACT" })).substeps).toEqual({
      total: 5,
      index: 0,
    });
    expect(phasesForJob(job({ plan: fullPlan, current_stage: "DISCOVER" })).substeps).toEqual({
      total: 5,
      index: 2,
    });
    // Verify covers VERIFY · ENRICH.
    expect(
      phasesForJob(job({ plan: fullPlan, current_stage: "VERIFY", state: "waiting_user" })).substeps,
    ).toEqual({ total: 2, index: 0 });
  });

  it("counts only the sub-stages this job's plan actually runs", () => {
    // Read here has just EXTRACT in the plan, so it is a single sub-step.
    const j = job({ plan: { stages: ["EXTRACT", "SCORE"] }, current_stage: "EXTRACT" });
    expect(phasesForJob(j).substeps).toEqual({ total: 1, index: 0 });
  });

  it("has no sub-steps when nothing is active", () => {
    expect(phasesForJob(job({ plan: fullPlan, current_stage: null, state: "queued" })).substeps).toBeNull();
    expect(phasesForJob(job({ plan: fullPlan, current_stage: "SCORE", state: "done" })).substeps).toBeNull();
  });

  it("marks the current phase cancelled and captions where it stopped", () => {
    const j = job({ plan: fullPlan, current_stage: "EXTRACT", state: "cancelled" });
    expect(statusOf(j, "fetch").status).toBe("done");
    const read = statusOf(j, "read");
    expect(read.status).toBe("active");
    expect(read.tone).toBe("cancelled");
    expect(statusOf(j, "verify").status).toBe("pending");
    expect(phasesForJob(j).caption).toBe("Cancelled while reading the listing");
    expect(phasesForJob(j).stageToken).toBe("EXTRACT");
  });

  it("shows phases absent from the job's plan as skipped (e.g. a rescore)", () => {
    const j = job({
      type: "rescore",
      plan: { stages: ["SCORE"] },
      current_stage: "SCORE",
      state: "running",
    });
    expect(statusOf(j, "prepare").status).toBe("skipped");
    expect(statusOf(j, "fetch").status).toBe("skipped");
    expect(statusOf(j, "read").status).toBe("skipped");
    expect(statusOf(j, "verify").status).toBe("skipped");
    expect(statusOf(j, "score").status).toBe("active");
    expect(phasesForJob(j).caption).toBe("Scoring…");
  });

  it("marks the current phase failed and leaves later phases pending", () => {
    const j = job({ plan: fullPlan, current_stage: "FETCH", state: "failed", error: "blocked" });
    expect(statusOf(j, "prepare").status).toBe("done");
    const fetch = statusOf(j, "fetch");
    expect(fetch.status).toBe("active");
    expect(fetch.tone).toBe("failed");
    expect(statusOf(j, "read").status).toBe("pending");
    expect(phasesForJob(j).caption).toBe("Stopped while fetching the page");
  });

  it("marks the current phase as waiting when parked on the user", () => {
    const j = job({ plan: fullPlan, current_stage: "VERIFY", state: "waiting_user" });
    expect(statusOf(j, "read").status).toBe("done");
    const verify = statusOf(j, "verify");
    expect(verify.status).toBe("active");
    expect(verify.tone).toBe("waiting");
    expect(phasesForJob(j).caption).toBe("Waiting for you");
  });

  it("marks every present phase done for a finished job", () => {
    const j = job({ plan: fullPlan, current_stage: "SCORE", state: "done" });
    for (const key of PHASE_ORDER) {
      expect(statusOf(j, key).status).toBe("done");
    }
    expect(phasesForJob(j).caption).toBeNull();
  });

  it("falls back to the legacy six-stage list when the job has no plan", () => {
    const j = job({ plan: null, current_stage: "extract", state: "running" });
    expect(statusOf(j, "prepare").status).toBe("done");
    expect(statusOf(j, "fetch").status).toBe("done");
    expect(statusOf(j, "read").status).toBe("active");
    expect(phasesForJob(j).caption).toBe("Reading the listing…");
  });

  it("shows a not-started track for a queued job", () => {
    const j = job({ plan: fullPlan, current_stage: null, state: "queued" });
    for (const key of PHASE_ORDER) {
      expect(statusOf(j, key).status).toBe("pending");
    }
    expect(phasesForJob(j).caption).toBe("Waiting to start");
    expect(phasesForJob(j).stageToken).toBeNull();
  });
});
