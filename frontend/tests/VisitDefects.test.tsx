import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const createDefect = vi.fn();
const patchDefect = vi.fn();
const deleteDefect = vi.fn();

vi.mock("../src/features/visits/api", () => ({
  useVisitDefects: () => ({ data: mockDefects, isLoading: false }),
  useCreateVisitDefect: () => ({ mutate: createDefect, isPending: false }),
  usePatchVisitDefect: () => ({ mutate: patchDefect, isPending: false }),
  useDeleteVisitDefect: () => ({ mutate: deleteDefect, isPending: false }),
}));

import { VisitDefects } from "../src/features/visits/VisitDefects";
import type { VisitDefect, VisitUnit } from "../src/features/visits/types";

const units: VisitUnit[] = [
  {
    id: "unit-a",
    visit_id: "v1",
    label: "4B",
    floor_plan_id: "fp1",
    beds: 2,
    baths: 2,
    unit_group_key: "2-2",
    display_order: 0,
    created_by: "me",
    created_at: "2026-07-30T08:00:00Z",
  },
];

function defect(partial: Partial<VisitDefect> = {}): VisitDefect {
  return {
    id: "d1",
    visit_id: "v1",
    visit_unit_id: null,
    from_item_key: null,
    title: "Water stain under the sink",
    note: null,
    severity: null,
    promised_in_writing: false,
    resolution: null,
    created_by: "me",
    created_at: "2026-07-30T10:00:00Z",
    deleted_at: null,
    ...partial,
  };
}

let mockDefects: VisitDefect[] = [];

/**
 * Mantine's `Rating` wires its **label**, not the hidden radio input, so
 * `userEvent.click` on the radio fires nothing under jsdom. Clicking the label
 * is what a real pointer does anyway; `stars[n]` is rating `n` (index 0 is the
 * "clear" option Rating renders first).
 */
function clickStar(container: HTMLElement, rating: number) {
  const labels = container.querySelectorAll("label");
  fireEvent.click(labels[rating]);
}

function render(props: Record<string, unknown> = {}) {
  return renderWithProviders(
    <VisitDefects visitId="v1" units={units} activeUnitId="unit-a" {...props} />,
  );
}

beforeEach(() => {
  createDefect.mockReset();
  patchDefect.mockReset();
  deleteDefect.mockReset();
  mockDefects = [];
});

describe("the defect log", () => {
  it("explains how it fills itself rather than showing a bare empty state", () => {
    render();
    expect(screen.getByText(/Marking a check as a problem records one here/)).toBeInTheDocument();
  });

  it("marks a promoted defect as coming from a check", () => {
    mockDefects = [defect({ from_item_key: "kitchen_disposal", visit_unit_id: "unit-a" })];
    render();
    expect(screen.getByText("From a check")).toBeInTheDocument();
    expect(screen.getByText("4B")).toBeInTheDocument();
  });

  it("does not mark a hand-logged defect as promoted", () => {
    mockDefects = [defect()];
    render();
    expect(screen.queryByText("From a check")).not.toBeInTheDocument();
  });

  it("says the building when a defect has no unit — that is a value, not a gap", () => {
    mockDefects = [defect({ visit_unit_id: null })];
    render();
    expect(screen.getByText("The building")).toBeInTheDocument();
  });

  it("counts how many logged themselves", () => {
    mockDefects = [
      defect({ id: "a", from_item_key: "k1" }),
      defect({ id: "b", from_item_key: "k2" }),
      defect({ id: "c" }),
    ];
    render();
    expect(screen.getByText(/2 of these logged themselves/)).toBeInTheDocument();
    expect(screen.getByText("3 defects")).toBeInTheDocument();
  });

  it("shows an unrated defect as unrated rather than as zero", () => {
    mockDefects = [defect({ severity: null })];
    render();
    expect(screen.getByText("unrated")).toBeInTheDocument();
  });

  it("clears the severity when the current rating is clicked again", () => {
    mockDefects = [defect({ severity: 3 })];
    const { container } = render();
    clickStar(container, 3);
    expect(patchDefect).toHaveBeenCalledWith({ defectId: "d1", body: { severity: null } });
  });

  it("sets a severity when a different rating is clicked", () => {
    mockDefects = [defect({ severity: null })];
    const { container } = render();
    clickStar(container, 4);
    expect(patchDefect).toHaveBeenCalledWith({ defectId: "d1", body: { severity: 4 } });
  });

  it("records a repair promise", async () => {
    mockDefects = [defect()];
    render();
    const user = userEvent.setup();
    await user.click(screen.getByRole("switch", { name: /Promised in writing/ }));
    expect(patchDefect).toHaveBeenCalledWith({
      defectId: "d1",
      body: { promised_in_writing: true },
    });
  });

  it("removes a defect, and says the check keeps its answer", async () => {
    mockDefects = [defect({ title: "Window won't latch" })];
    render();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Remove defect: Window won't latch/ }));
    expect(deleteDefect).toHaveBeenCalledWith("d1");
  });

  it("logs something the checklist never asked about, attached to the active unit", async () => {
    render();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Log something else/ }));
    await user.type(screen.getByRole("textbox", { name: /What's wrong/ }), "Fresh caulk");
    await user.click(screen.getByRole("button", { name: "Log it" }));
    expect(createDefect).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Fresh caulk", visit_unit_id: "unit-a" }),
      expect.anything(),
    );
  });

  it("can attach a hand-logged defect to the building instead", async () => {
    render();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Log something else/ }));
    await user.type(screen.getByRole("textbox", { name: /What's wrong/ }), "Trash area");
    await user.click(screen.getByRole("switch", { name: /Attach to 4B/ }));
    await user.click(screen.getByRole("button", { name: "Log it" }));
    expect(createDefect).toHaveBeenCalledWith(
      expect.objectContaining({ visit_unit_id: null }),
      expect.anything(),
    );
  });

  it("will not log a blank defect", async () => {
    render();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Log something else/ }));
    expect(screen.getByRole("button", { name: "Log it" })).toBeDisabled();
  });

  it("offers no edits at all on a finished visit", () => {
    mockDefects = [defect()];
    render({ readOnly: true });
    expect(screen.queryByRole("button", { name: /Remove defect/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Log something else/ })).not.toBeInTheDocument();
    // The switch goes rather than greys — the green badge already states the
    // promise, and a dead switch beside it only muddies the record.
    expect(screen.queryByRole("switch", { name: /Promised in writing/ })).not.toBeInTheDocument();
  });
});
