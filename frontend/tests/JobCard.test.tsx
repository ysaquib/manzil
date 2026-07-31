import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import { checkpointAnswer, type Job } from "../src/features/jobs/api";
import { AutoResolvedCheckpointReview } from "../src/features/jobs/AutoResolvedCheckpointReview";
import { CheckpointPromptCard } from "../src/features/jobs/CheckpointPromptCard";
import { isCancellable, JobCard, STATE_COLOR } from "../src/features/jobs/JobCard";

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

const noop = () => {};

function renderCard(j: Job) {
  return renderWithProviders(
    <JobCard
      job={j}
      listingName="The Test Flats"
      onCancel={noop}
      onRetry={noop}
      onAnswer={noop}
      busy={false}
    />,
  );
}

describe("job state mapping", () => {
  it("covers every job state with a color", () => {
    expect(Object.keys(STATE_COLOR).sort()).toEqual(
      ["cancelled", "done", "failed", "queued", "running", "waiting_user"].sort(),
    );
  });

  it("only live states are cancellable", () => {
    expect(isCancellable("queued")).toBe(true);
    expect(isCancellable("running")).toBe(true);
    expect(isCancellable("waiting_user")).toBe(true);
    expect(isCancellable("done")).toBe(false);
    expect(isCancellable("failed")).toBe(false);
    expect(isCancellable("cancelled")).toBe(false);
  });

  it("shows stage progress and cancel for a running job", () => {
    renderCard(job());
    expect(screen.getByText("Reading the listing…")).toBeInTheDocument();
    expect(screen.getByText("EXTRACT")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("shows retry and the error for a failed job", () => {
    renderCard(job({ state: "failed", error: "fetch blocked" }));
    expect(screen.getByText("fetch blocked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("renders the checkpoint prompt inline when waiting on the user", () => {
    renderCard(
      job({
        state: "waiting_user",
        checkpoint: {
          kind: "confirm_value",
          question: "Does $2,450 look right?",
          options: ["yes", "no"],
          default: "yes",
        },
        checkpoint_context: {
          evidence: [
            {
              value: 2450,
              evidence_quote: "$2,450 monthly rent",
              source_url: "https://example.com/listing",
            },
          ],
        },
      }),
    );
    expect(screen.getByText("Does $2,450 look right?")).toBeInTheDocument();
    expect(screen.getByText("“$2,450 monthly rent”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /example.com/ })).toHaveAttribute(
      "href",
      "https://example.com/listing",
    );
    expect(screen.getByRole("button", { name: "yes" })).toBeInTheDocument();
  });
});

describe("auto-resolved checkpoint review", () => {
  it("shows the applied default and accepts a late correction", async () => {
    const onAnswer = vi.fn();
    renderWithProviders(
      <AutoResolvedCheckpointReview
        checkpoint={{
          prompt: {
            kind: "resolve_dispute",
            question: "Which rent should be used?",
            options: ["$2,400", "Leave unknown"],
            default: "Leave unknown",
          },
          answer: { choice: "Leave unknown" },
          resolved_at: "2026-07-30T12:00:00Z",
          context: { evidence: [] },
        }}
        canAnswer
        answering={false}
        onAnswer={onAnswer}
      />,
    );
    expect(screen.getByText(/Auto-resolved after 24 hours/)).toHaveTextContent(
      "Leave unknown",
    );
    await userEvent.click(screen.getByRole("button", { name: "$2,400" }));
    expect(onAnswer).toHaveBeenCalledWith("$2,400");
  });
});

describe("checkpoint answering", () => {
  it("builds the §10.10 answer payload", () => {
    expect(checkpointAnswer("yes")).toEqual({ answer: { choice: "yes" } });
    expect(checkpointAnswer("other", "call the office")).toEqual({
      answer: { choice: "other", text: "call the office" },
    });
  });

  it("fires onAnswer with the picked option", async () => {
    const onAnswer = vi.fn();
    renderWithProviders(
      <CheckpointPromptCard
        prompt={{
          kind: "confirm_value",
          question: "Confirm?",
          options: ["yes", "no", "other:<input>"],
          default: "yes",
        }}
        onAnswer={onAnswer}
        answering={false}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "no" }));
    expect(onAnswer).toHaveBeenCalledWith("no");

    await userEvent.type(screen.getByPlaceholderText("Something else…"), "check site");
    await userEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(onAnswer).toHaveBeenCalledWith("other", "check site");
  });
});

describe("run warnings", () => {
  it("shows a non-fatal warning without dressing it up as a failure", () => {
    renderCard(
      job({
        warnings: [
          {
            stage: "IMAGE_CLASSIFY",
            code: "classification_missing",
            message: "The classifier skipped 2 of 30 photos.",
          },
        ],
      }),
    );
    expect(screen.getByText("The classifier skipped 2 of 30 photos.")).toBeInTheDocument();
    // Still a live run: the warning changed nothing about the job's state.
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("renders nothing when a run is clean", () => {
    const { container } = renderCard(job());
    expect(container.querySelectorAll(".tabler-icon-alert-triangle")).toHaveLength(0);
  });
});
