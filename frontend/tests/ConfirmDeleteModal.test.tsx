// The confirmation is the only thing standing between an operator and an
// unrecoverable delete, so the tests are about what it refuses, not what it
// renders: the wrong name, the missing phrase, and the row that cannot go.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ConfirmDeleteModal,
  bulkConfirmationPhrase,
  type DeletionTarget,
} from "../src/components/ConfirmDeleteModal";
import { renderWithProviders } from "./testUtils";

const HUNTS = { singular: "hunt", plural: "hunts" };

function targets(count: number): DeletionTarget[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `h${index}`,
    label: `Hunt ${index}`,
    description: `${index} listings`,
  }));
}

describe("ConfirmDeleteModal", () => {
  it("asks for the subject's own name when there is exactly one", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderWithProviders(
      <ConfirmDeleteModal
        opened
        onClose={() => {}}
        noun={HUNTS}
        targets={targets(1)}
        onConfirm={onConfirm}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Hunt 0")).toBeInTheDocument();

    const confirm = within(dialog).getByRole("button", { name: "Permanently delete 1 hunt" });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByLabelText(/Type/), "hunt 0");
    expect(within(dialog).getByText("That name does not match")).toBeInTheDocument();
    expect(confirm).toBeDisabled();

    await user.clear(within(dialog).getByLabelText(/Type/));
    await user.type(within(dialog).getByLabelText(/Type/), "Hunt 0");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith([expect.objectContaining({ id: "h0" })]);
  });

  it("shows every subject in a scrollable pane and asks for the fixed phrase", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderWithProviders(
      <ConfirmDeleteModal
        opened
        onClose={() => {}}
        noun={HUNTS}
        targets={targets(12)}
        onConfirm={onConfirm}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    // All twelve are listed — the pane scrolls, it does not truncate.
    expect(within(dialog).getByText("About to delete (12)")).toBeInTheDocument();
    expect(within(dialog).getByText("Hunt 0")).toBeInTheDocument();
    expect(within(dialog).getByText("Hunt 11")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("hunts to delete")).toBeInTheDocument();

    const confirm = within(dialog).getByRole("button", { name: "Permanently delete 12 hunts" });
    expect(confirm).toBeDisabled();

    // A single name is not enough once there is more than one subject.
    await user.type(within(dialog).getByLabelText(/Type/), "Hunt 0");
    expect(confirm).toBeDisabled();

    await user.clear(within(dialog).getByLabelText(/Type/));
    await user.type(within(dialog).getByLabelText(/Type/), "Permanently Delete All Selected Hunts");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    expect(onConfirm.mock.calls[0]?.[0]).toHaveLength(12);
  });

  it("lists a blocked subject with its reason and never passes it on", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderWithProviders(
      <ConfirmDeleteModal
        opened
        onClose={() => {}}
        noun={HUNTS}
        targets={[
          ...targets(2),
          { id: "blocked", label: "Jersey City", blockedReason: "has a running Job" },
        ]}
        onConfirm={onConfirm}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Jersey City")).toBeInTheDocument();
    expect(within(dialog).getByText(/has a running Job/)).toBeInTheDocument();
    expect(
      within(dialog).getByText(/1 of 3 cannot be deleted and will be skipped/),
    ).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/Type/), bulkConfirmationPhrase(HUNTS));
    await user.click(within(dialog).getByRole("button", { name: "Permanently delete 2 hunts" }));

    expect(onConfirm).toHaveBeenCalledWith([
      expect.objectContaining({ id: "h0" }),
      expect.objectContaining({ id: "h1" }),
    ]);
  });

  it("skips the typing for a reversible removal but still shows the subject", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    renderWithProviders(
      <ConfirmDeleteModal
        opened
        onClose={() => {}}
        noun={{ singular: "membership", plural: "memberships" }}
        title="Remove from this Hunt?"
        confirmLabel="Remove"
        requireTypedConfirmation={false}
        targets={[{ id: "h1", label: "Brooklyn 2026" }]}
        onConfirm={onConfirm}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Brooklyn 2026")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/Type/)).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("forgets a typed phrase when the selection changes", async () => {
    const user = userEvent.setup();

    function Harness() {
      const [current, setCurrent] = useState(targets(1));
      return (
        <>
          <button onClick={() => setCurrent([{ id: "other", label: "Hunt 9" }])}>swap</button>
          <ConfirmDeleteModal
            opened
            onClose={() => {}}
            noun={HUNTS}
            targets={current}
            onConfirm={() => {}}
          />
        </>
      );
    }

    renderWithProviders(<Harness />);

    await user.type(await screen.findByLabelText(/Type/), "Hunt 0");
    expect(screen.getByRole("button", { name: "Permanently delete 1 hunt" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "swap" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Permanently delete 1 hunt" })).toBeDisabled(),
    );
    expect(screen.getByLabelText(/Type/)).toHaveValue("");
  });
});
