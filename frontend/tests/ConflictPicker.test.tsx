// The conflict surface (VC-6).
//
// The rule under test throughout: nothing is discarded and nothing is guessed.
// Both values are shown, attributed, and a human picks.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { HuntMember } from "../src/features/collaboration/api";
import {
  ConflictPicker,
  branchValueLabel,
  groupForks,
} from "../src/features/visits/ConflictPicker";
import type { VisitEntryConflict, VisitItem, VisitUnit } from "../src/features/visits/types";
import { renderWithProviders } from "./testUtils";

const members: HuntMember[] = [
  { hunt_id: "h1", user_id: "me", role: "owner", color: "plum", display_name: "Yusuf" },
  { hunt_id: "h1", user_id: "you", role: "member", color: "ochre", display_name: "Sana" },
];

const items = [
  { key: "ess_parking", label: "Parking works", kind: "check", scope: "property" },
] as unknown as VisitItem[];

const units = [{ id: "unit-a", label: "4B" }] as unknown as VisitUnit[];

function branch(partial: Partial<VisitEntryConflict>): VisitEntryConflict {
  return {
    id: "b1",
    visit_id: "v1",
    item_key: "ess_parking",
    is_custom: false,
    visit_unit_id: null,
    owner_user_id: null,
    author_user_id: "me",
    value: "ok",
    answer_text: null,
    note: null,
    created_at: "2026-07-30T10:00:00Z",
    fork_parent_id: "parent-1",
    ...partial,
  };
}

const twoWay = [
  branch({ id: "b1", author_user_id: "me", value: "problem" }),
  branch({ id: "b2", author_user_id: "you", value: "ok", created_at: "2026-07-30T10:00:05Z" }),
];

describe("groupForks", () => {
  it("gathers the branches of one contested answer", () => {
    const forks = groupForks(twoWay);
    expect(forks).toHaveLength(1);
    expect(forks[0]!.branches.map((b) => b.id)).toEqual(["b1", "b2"]);
  });

  it("keeps separate answers separate", () => {
    const forks = groupForks([...twoWay, branch({ id: "c1", fork_parent_id: "parent-2" })]);
    expect(forks).toHaveLength(2);
  });

  it("orders branches by when they landed, so the story reads forwards", () => {
    const forks = groupForks([twoWay[1]!, twoWay[0]!]);
    expect(forks[0]!.branches.map((b) => b.id)).toEqual(["b1", "b2"]);
  });
});

describe("branchValueLabel", () => {
  it("reads a check state in the same words the control used", () => {
    // A Check stores "ok" but the tri-state control says "Fine"; showing the
    // stored token here would make the reader choose between an answer and a
    // synonym for it.
    expect(branchValueLabel(branch({ value: "problem" }))).toBe("Problem");
    expect(branchValueLabel(branch({ value: "ok" }))).toBe("Fine");
  });

  it("says a cleared answer is cleared, because that is a real choice", () => {
    // The tombstone means "nobody has looked" — rendering it blank would make
    // the branch look like a rendering bug rather than an answer.
    expect(branchValueLabel(branch({ value: null }))).toBe("Cleared");
  });

  it("prefers a question's typed answer", () => {
    expect(branchValueLabel(branch({ value: null, answer_text: "No, never" }))).toBe("No, never");
  });
});

describe("ConflictPicker", () => {
  it("renders nothing when nothing is contested — the common case", () => {
    renderWithProviders(
      <ConflictPicker
        conflicts={[]}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={vi.fn()}
      />,
    );
    expect(screen.queryByText(/needs a decision/)).not.toBeInTheDocument();
  });

  it("shows both values, attributed, rather than picking one", () => {
    renderWithProviders(
      <ConflictPicker
        conflicts={twoWay}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={vi.fn()}
      />,
    );
    expect(screen.getByText("One answer needs a decision")).toBeInTheDocument();
    expect(screen.getByText("Parking works")).toBeInTheDocument();
    expect(screen.getByText("Problem")).toBeInTheDocument();
    expect(screen.getByText("Fine")).toBeInTheDocument();
    expect(screen.getByText(/You ·/)).toBeInTheDocument();
    expect(screen.getByText(/Sana ·/)).toBeInTheDocument();
  });

  it("resolves to the branch the reader chose", async () => {
    const onResolve = vi.fn();
    renderWithProviders(
      <ConflictPicker
        conflicts={twoWay}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={onResolve}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: /Problem/ }));
    await user.click(screen.getByRole("button", { name: "Keep this answer" }));

    expect(onResolve).toHaveBeenCalledWith(expect.objectContaining({ id: "b1", value: "problem" }));
  });

  it("defaults to the newest branch, so confirming changes nothing by itself", () => {
    // The newest is what the checklist is already showing; a default that
    // silently flipped the value would be worse than no default.
    renderWithProviders(
      <ConflictPicker
        conflicts={twoWay}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={vi.fn()}
      />,
    );
    expect(screen.getByRole("radio", { name: /Fine/ })).toBeChecked();
  });

  it("names the unit a contested unit-scoped answer belongs to", () => {
    renderWithProviders(
      <ConflictPicker
        conflicts={[
          branch({ id: "u1", visit_unit_id: "unit-a" }),
          branch({ id: "u2", visit_unit_id: "unit-a", value: "problem" }),
        ]}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={vi.fn()}
      />,
    );
    expect(screen.getByText("4B")).toBeInTheDocument();
  });

  it("counts multiple contested answers instead of burying them", () => {
    renderWithProviders(
      <ConflictPicker
        conflicts={[...twoWay, branch({ id: "c1", fork_parent_id: "parent-2" }), branch({ id: "c2", fork_parent_id: "parent-2", value: "problem" })]}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={vi.fn()}
      />,
    );
    expect(screen.getByText("2 answers need a decision")).toBeInTheDocument();
  });

  it("handles a three-way fork, which two offline members can produce", () => {
    renderWithProviders(
      <ConflictPicker
        conflicts={[
          branch({ id: "t1", value: "ok" }),
          branch({ id: "t2", value: "problem" }),
          branch({ id: "t3", value: null }),
        ]}
        items={items}
        units={units}
        members={members}
        viewerId="me"
        onResolve={vi.fn()}
      />,
    );
    const group = screen.getByRole("radiogroup");
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
  });
});
