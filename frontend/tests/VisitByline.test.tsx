import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HuntMember } from "../src/features/collaboration/api";
import type { VisitEntry } from "../src/features/visits/types";
import { VisitByline } from "../src/features/visits/VisitByline";
import { renderWithProviders } from "./testUtils";

const members: HuntMember[] = [
  { hunt_id: "h1", user_id: "me", role: "owner", color: "plum", display_name: "Yusuf" },
  { hunt_id: "h1", user_id: "you", role: "member", color: "ochre", display_name: "Sana" },
];

function entry(partial: Partial<VisitEntry> = {}): VisitEntry {
  return {
    id: "e1",
    visit_id: "v1",
    item_key: "kitchen_disposal",
    is_custom: false,
    visit_unit_id: null,
    owner_user_id: null,
    author_user_id: "you",
    value: "ok",
    answer_text: null,
    note: null,
    prev_entry_id: null,
    created_at: new Date(Date.now() - 60_000).toISOString(),
    ...partial,
  };
}

describe("VisitByline", () => {
  it("names another member as the author of a shared answer", () => {
    renderWithProviders(
      <VisitByline entry={entry()} members={members} viewerId="me" />,
    );
    expect(screen.getByText(/Sana/)).toBeInTheDocument();
  });

  it("says 'You' for your own write — the byline is about who else touched it", () => {
    renderWithProviders(
      <VisitByline entry={entry({ author_user_id: "me" })} members={members} viewerId="me" />,
    );
    expect(screen.getByText(/You/)).toBeInTheDocument();
    expect(screen.queryByText(/Yusuf/)).not.toBeInTheDocument();
  });

  it("never presents an unknown retained author as a current Member", () => {
    renderWithProviders(
      <VisitByline entry={entry({ author_user_id: "gone" })} members={members} viewerId="me" />,
    );
    expect(screen.getByText(/Former User/)).toBeInTheDocument();
  });

  it("shows when, relatively — 'a minute ago' beats a timestamp mid-tour", () => {
    renderWithProviders(<VisitByline entry={entry()} members={members} viewerId="me" />);
    expect(screen.getByText(/ago/)).toBeInTheDocument();
  });
});
