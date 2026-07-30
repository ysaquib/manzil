import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import { PipelineTrack } from "../src/features/jobs/PipelineTrack";
import type { Job } from "../src/features/jobs/api";
import { phasesForJob } from "../src/features/jobs/pipelinePhases";

const FULL_PLAN = {
  stages: [
    "PLAN",
    "VALIDATE_URL",
    "FETCH",
    "VALIDATE",
    "EXTRACT",
    "DEDUPE",
    "DISCOVER",
    "FETCH",
    "EXTRACT",
    "VERIFY",
    "RECONCILE",
    "IMAGE_FETCH",
    "IMAGE_CLASSIFY",
    "VISION",
    "ENRICH",
    "SCORE",
  ],
};

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
    plan: FULL_PLAN,
    ...overrides,
  };
}

describe("PipelineTrack", () => {
  it("renders manifest fraction for the active phase's stage position", () => {
    const j = job({ current_stage: "DISCOVER", stage_index: 6, state: "running" });
    renderWithProviders(<PipelineTrack model={phasesForJob(j)} />);
    expect(screen.getByText("DISCOVER · 7/16")).toBeInTheDocument();
  });

  it("renders manifest fraction on the second FETCH after DISCOVER", () => {
    const j = job({ current_stage: "FETCH", stage_index: 7, state: "running" });
    renderWithProviders(<PipelineTrack model={phasesForJob(j)} />);
    expect(screen.getByText("FETCH · 8/16")).toBeInTheDocument();
  });

  it("shows no expand affordance when not expandable", () => {
    renderWithProviders(<PipelineTrack model={phasesForJob(job())} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("toggles the timeline region when expandable", async () => {
    const onToggle = vi.fn();
    const { rerender } = renderWithProviders(
      <PipelineTrack model={phasesForJob(job({ state: "done" }))} expandable expanded={false} onToggle={onToggle}>
        <div>the timeline</div>
      </PipelineTrack>,
    );
    const region = screen.getByRole("button");
    expect(region).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("the timeline")).not.toBeInTheDocument();

    await userEvent.click(region);
    expect(onToggle).toHaveBeenCalledOnce();

    rerender(
      <PipelineTrack model={phasesForJob(job({ state: "done" }))} expandable expanded onToggle={onToggle}>
        <div>the timeline</div>
      </PipelineTrack>,
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("the timeline")).toBeInTheDocument();
  });
});
