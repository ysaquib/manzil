import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../../../tests/testUtils";
import { PipelineTrack } from "./PipelineTrack";
import type { Job } from "./api";
import { phasesForJob } from "./pipelinePhases";

const FULL_PLAN = {
  stages: ["PLAN", "VALIDATE_URL", "FETCH", "VALIDATE", "EXTRACT", "DEDUPE", "DISCOVER", "IMAGE_FETCH", "VISION", "VERIFY", "ENRICH", "SCORE"],
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
  it("renders sub-pips and a fraction for the active phase's stage position", () => {
    const j = job({ current_stage: "DISCOVER", state: "running" });
    const { container } = renderWithProviders(<PipelineTrack model={phasesForJob(j)} />);
    // Read runs 5 stages; DISCOVER is the 3rd.
    expect(container.querySelectorAll("[data-s]")).toHaveLength(5);
    expect(screen.getByText("DISCOVER · 3/5")).toBeInTheDocument();
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
