// AD-3: the roster and, mostly, the refusal.
//
// Deleting an account that owns a Hunt takes the Hunt and everything under it,
// and there is no undo. The API refuses it — these tests are about the UI
// saying so *before* the click rather than surfacing an error after it.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class extends Error {},
}));

import { AdminPeoplePage } from "../src/features/admin/AdminPeoplePage";

const OWNER = {
  user_id: "u-owner",
  email: "owner@example.com",
  display_name: "N. Rahman",
  confirmed: true,
  suspended: false,
  hunts: 2,
  owns: 1,
  created_at: "2026-07-14T00:00:00Z",
  last_sign_in_at: "2026-07-31T00:00:00Z",
  spend_usd: 11.22,
  is_site_admin: false,
};

const PLAIN = {
  ...OWNER,
  user_id: "u-plain",
  email: "plain@example.com",
  display_name: "A. Osei",
  hunts: 1,
  owns: 0,
  spend_usd: 0,
};

const OWNER_DETAIL = {
  ...OWNER,
  feedback_count: 3,
  memberships: [
    { hunt_id: "h1", hunt_name: "Jersey City", role: "owner", joined_at: null },
    { hunt_id: "h2", hunt_name: "Brooklyn 2026", role: "curator", joined_at: null },
  ],
  blocking_owned_hunts: [
    { hunt_id: "h1", hunt_name: "Jersey City", role: "owner", joined_at: null },
  ],
};

const PLAIN_DETAIL = {
  ...PLAIN,
  feedback_count: 0,
  memberships: [
    { hunt_id: "h2", hunt_name: "Brooklyn 2026", role: "member", joined_at: null },
  ],
  blocking_owned_hunts: [],
};

function route(path: string) {
  if (path.startsWith("/v1/admin/people/u-owner")) return Promise.resolve(OWNER_DETAIL);
  if (path.startsWith("/v1/admin/people/u-plain")) return Promise.resolve(PLAIN_DETAIL);
  if (path.startsWith("/v1/admin/people")) return Promise.resolve([OWNER, PLAIN]);
  if (path.startsWith("/v1/admin/hunts")) {
    return Promise.resolve([
      { hunt_id: "h1", name: "Jersey City" },
      { hunt_id: "h2", name: "Brooklyn 2026" },
    ]);
  }
  return Promise.resolve({});
}

describe("AdminPeoplePage", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockImplementation((path: string) => route(path));
  });

  it("shows who owns what, since owning is what constrains every other action", async () => {
    renderWithProviders(<AdminPeoplePage />);

    expect(await screen.findByText("N. Rahman")).toBeInTheDocument();
    expect(screen.getByText("(1 own)")).toBeInTheDocument();
    expect(screen.getByText("$11.22")).toBeInTheDocument();
  });

  it("disables Delete for a Hunt owner and names the Hunt blocking it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminPeoplePage />);

    await user.click(await screen.findByText("N. Rahman"));

    const deleteButton = await screen.findByRole("button", { name: "Delete" });
    expect(deleteButton).toBeDisabled();
    // The reason is on screen, not only in a tooltip that needs discovering.
    expect(await screen.findByText(/would take Jersey City/)).toBeInTheDocument();

    await user.click(deleteButton);
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/v1/admin/people/u-owner",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("enables Delete for someone who owns nothing", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminPeoplePage />);

    await user.click(await screen.findByText("A. Osei"));

    const deleteButton = await screen.findByRole("button", { name: "Delete" });
    expect(deleteButton).toBeEnabled();
    expect(screen.queryByText(/would take/)).not.toBeInTheDocument();

    await user.click(deleteButton);
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/people/u-plain", {
        method: "DELETE",
      }),
    );
  });

  it("refuses to remove the Owner from their own Hunt", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminPeoplePage />);
    await user.click(await screen.findByText("N. Rahman"));

    // "Jersey City" also appears in the blocking alert and the Hunt picker, so
    // scope to the memberships table rather than matching on text alone.
    const membershipRow = (name: string) =>
      screen
        .getAllByText(name)
        .map((node) => node.closest("tr"))
        .find((row): row is HTMLTableRowElement => row !== null);

    const ownerRow = membershipRow("Jersey City");
    expect(ownerRow).toBeDefined();
    expect(within(ownerRow as HTMLElement).getByRole("button")).toBeDisabled();

    // ...but an ordinary membership is removable.
    const curatorRow = membershipRow("Brooklyn 2026");
    expect(within(curatorRow as HTMLElement).getByRole("button")).toBeEnabled();
  });

  it("offers Suspend as the reversible alternative and flips to Restore", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminPeoplePage />);
    await user.click(await screen.findByText("A. Osei"));

    await user.click(await screen.findByRole("button", { name: "Suspend" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/people/u-plain/suspend", {
        method: "POST",
      }),
    );
  });
});
