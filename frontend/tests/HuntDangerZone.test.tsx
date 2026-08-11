import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useLeaveHunt = vi.hoisted(() => vi.fn());
const useTransferOwnership = vi.hoisted(() => vi.fn());
const usePatchHunt = vi.hoisted(() => vi.fn());
const leave = vi.hoisted(() => vi.fn());

vi.mock("../src/features/collaboration/api", () => ({ useLeaveHunt, useTransferOwnership }));
vi.mock("../src/features/hunts/api", () => ({ usePatchHunt }));

import { HuntDangerZone } from "../src/features/hunts/HuntDangerZone";
import type { HuntMember } from "../src/features/collaboration/api";
import type { Hunt } from "../src/features/hunts/api";

const HUNT = { id: "h1", name: "Detroit apartments" } as Hunt;

const owner: HuntMember = {
  hunt_id: "h1",
  user_id: "u-owner",
  role: "owner",
  color: "moss",
  display_name: "Yusuf",
};
const member: HuntMember = {
  hunt_id: "h1",
  user_id: "u-member",
  role: "member",
  color: "ochre",
  display_name: "Sam",
};

function renderZone(props: Partial<Parameters<typeof HuntDangerZone>[0]> = {}) {
  return renderWithProviders(
    <MemoryRouter>
      <HuntDangerZone
        hunt={HUNT}
        members={[owner, member]}
        currentUserId="u-owner"
        isOwner={true}
        isGhost={false}
        {...props}
      />
    </MemoryRouter>,
  );
}

const archiveButton = () => screen.getByRole("button", { name: "Archive hunt…" });
const leaveButton = () => screen.getByRole("button", { name: "Leave hunt…" });

describe("HuntDangerZone", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLeaveHunt.mockReturnValue({ mutate: leave, isPending: false });
    useTransferOwnership.mockReturnValue({ mutate: vi.fn(), isPending: false });
    usePatchHunt.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it("makes the Owner transfer ownership before they can leave", () => {
    renderZone();
    expect(leaveButton()).toBeDisabled();
    expect(
      screen.getByText("Transfer ownership to another member before you can leave."),
    ).toBeInTheDocument();
    // The way out is offered right beside the refusal.
    expect(screen.getAllByLabelText("Transfer ownership to").length).toBeGreaterThan(0);
  });

  it("tells a hunt's only member to archive instead of leaving", () => {
    renderZone({ members: [owner] });
    expect(leaveButton()).toBeDisabled();
    expect(
      screen.getByText(
        "You're the only member of this hunt, so there is nobody to leave it to. Archive it instead.",
      ),
    ).toBeInTheDocument();
    // Archiving is the action they are being sent to, so it must be available.
    expect(archiveButton()).toBeEnabled();
  });

  it("lets a non-owner leave but not archive", () => {
    renderZone({ currentUserId: "u-member", isOwner: false });
    expect(leaveButton()).toBeEnabled();
    expect(archiveButton()).toBeDisabled();
    expect(screen.getByText("Only the Owner can archive this hunt.")).toBeInTheDocument();
    // Transfer is the Owner's alone and is absent entirely for everyone else.
    expect(screen.queryAllByLabelText("Transfer ownership to")).toHaveLength(0);
  });

  it("leaves only after the confirmation naming the hunt", async () => {
    const user = userEvent.setup();
    renderZone({ currentUserId: "u-member", isOwner: false });
    await user.click(leaveButton());

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Detroit apartments")).toBeInTheDocument();
    expect(leave).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Leave hunt" }));
    expect(leave).toHaveBeenCalledTimes(1);
  });

  it("offers no leave control in Ghost View, which has no membership to end", () => {
    renderZone({ currentUserId: "admin", isGhost: true, isOwner: true });
    expect(screen.queryByRole("button", { name: "Leave hunt…" })).not.toBeInTheDocument();
  });

  it("keeps the leave control disabled until the roster is known", () => {
    renderZone({ members: [], currentUserId: "u-member", isOwner: false });
    expect(leaveButton()).toBeDisabled();
  });
});
