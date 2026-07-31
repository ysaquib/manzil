import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VisitConfirmDialog } from "../src/features/visits/VisitConfirmDialog";
import { renderWithProviders } from "./testUtils";

describe("VisitConfirmDialog", () => {
  it("passes an optional reason through when one is collected", async () => {
    const onConfirm = vi.fn();
    renderWithProviders(
      <VisitConfirmDialog
        opened
        onClose={() => {}}
        title="Cancel this visit?"
        body="Cancelling is not deleting."
        confirmLabel="Cancel visit"
        reasonLabel="Why? (optional)"
        onConfirm={onConfirm}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /Why/ }), "  agent no-show  ");
    await user.click(screen.getByRole("button", { name: "Cancel visit" }));
    expect(onConfirm).toHaveBeenCalledWith("agent no-show");
  });

  it("treats a blank reason as no reason rather than an empty string", async () => {
    const onConfirm = vi.fn();
    renderWithProviders(
      <VisitConfirmDialog
        opened
        onClose={() => {}}
        title="Cancel this visit?"
        body="Cancelling is not deleting."
        confirmLabel="Cancel visit"
        reasonLabel="Why? (optional)"
        onConfirm={onConfirm}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /Why/ }), "   ");
    await user.click(screen.getByRole("button", { name: "Cancel visit" }));
    expect(onConfirm).toHaveBeenCalledWith(undefined);
  });

  it("collects no reason when none is asked for", async () => {
    const onConfirm = vi.fn();
    renderWithProviders(
      <VisitConfirmDialog
        opened
        onClose={() => {}}
        title="Delete this visit?"
        body="This is permanent."
        confirmLabel="Delete permanently"
        onConfirm={onConfirm}
      />,
    );
    const user = userEvent.setup();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect(onConfirm).toHaveBeenCalledWith(undefined);
  });

  it("backing out closes without confirming", async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    renderWithProviders(
      <VisitConfirmDialog
        opened
        onClose={onClose}
        title="Delete this visit?"
        body="This is permanent."
        confirmLabel="Delete permanently"
        onConfirm={onConfirm}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(onClose).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("renders nothing while closed", () => {
    renderWithProviders(
      <VisitConfirmDialog
        opened={false}
        onClose={() => {}}
        title="Delete this visit?"
        body="This is permanent."
        confirmLabel="Delete permanently"
        onConfirm={() => {}}
      />,
    );
    expect(screen.queryByText("Delete this visit?")).not.toBeInTheDocument();
  });
});
