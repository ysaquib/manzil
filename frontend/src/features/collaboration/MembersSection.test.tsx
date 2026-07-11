import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  useSetMemberRole: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveMember: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { MembersSection } from "./MembersSection";
import type { HuntMember } from "./api";

const owner: HuntMember = {
  hunt_id: "h1",
  user_id: "u-owner",
  role: "owner",
  color: "dusk",
  display_name: "Yusuf",
};
const member: HuntMember = {
  hunt_id: "h1",
  user_id: "u-member",
  role: "member",
  color: "moss",
  display_name: "Sam",
};

function renderSection(props: Partial<Parameters<typeof MembersSection>[0]> = {}) {
  return render(
    <MantineProvider>
      <MembersSection
        huntId="h1"
        members={[owner, member]}
        currentUserId="u-owner"
        isOwner={true}
        {...props}
      />
    </MantineProvider>,
  );
}

describe("MembersSection", () => {
  it("shows the full roster with display names", () => {
    renderSection();
    expect(screen.getByText("Yusuf")).toBeInTheDocument();
    expect(screen.getByText("Sam")).toBeInTheDocument();
  });

  it("gives the owner a role Select and Remove on other non-owner rows only", () => {
    renderSection();
    // The other Member's row has a role Select (Mantine renders a visible +
    // hidden input, so query for at least one) and a Remove button.
    expect(screen.getAllByLabelText("Role for Sam").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
    // Exactly one Remove button — the owner's own row never gets one.
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
    // The owner row shows a static Owner badge, not a Select.
    expect(screen.queryAllByLabelText("Role for Yusuf")).toHaveLength(0);
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("renders a read-only roster for non-owners", () => {
    renderSection({ isOwner: false, currentUserId: "u-member" });
    expect(screen.queryAllByLabelText("Role for Sam")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Member")).toBeInTheDocument();
  });

  it("falls back to 'Member' when a display name is missing", () => {
    renderSection({
      members: [owner, { ...member, display_name: null }],
    });
    // The nameless row is addressed as "Member" (in the row label and its text).
    expect(screen.getAllByLabelText("Role for Member").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Member").length).toBeGreaterThan(0);
  });
});
