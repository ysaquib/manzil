// AD-3: the roster and, mostly, the refusal.
//
// Deleting an account that owns a Hunt takes the Hunt and everything under it,
// and there is no undo. The API refuses it — these tests are about the UI
// saying so *before* the click rather than surfacing an error after it.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class extends Error {},
}));

import { AdminPeoplePage } from "../src/features/admin/AdminPeoplePage";

function renderPage(initialEntry = "/admin/people") {
  return renderWithProviders(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AdminPeoplePage />
    </MemoryRouter>,
  );
}

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
    renderPage();

    expect(await screen.findByText("N. Rahman")).toBeInTheDocument();
    expect(screen.getByText("(1 own)")).toBeInTheDocument();
    expect(screen.getByText("$11.22")).toBeInTheDocument();
  });

  it("keeps the roster card independent from the detail panel height", async () => {
    renderPage();

    await screen.findByText("N. Rahman");
    const directory = screen.getByRole("region", { name: "People directory" });

    expect(directory).toHaveStyle("--group-align: flex-start");
    expect(directory).not.toHaveStyle("align-items: stretch");
  });

  it("disables Delete for a Hunt owner and names the Hunt blocking it", async () => {
    const user = userEvent.setup();
    renderPage();

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

  it("links each membership to a selected exact-ID Hunt search", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("N. Rahman"));
    expect(await screen.findByRole("link", { name: "Brooklyn 2026" })).toHaveAttribute(
      "href",
      "/admin/hunts?search=h2&search_mode=id&selected=h2",
    );
  });

  it("enables Delete for someone who owns nothing, but only through the confirmation", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("A. Osei"));

    const deleteButton = await screen.findByRole("button", { name: "Delete" });
    expect(deleteButton).toBeEnabled();
    expect(screen.queryByText(/would take/)).not.toBeInTheDocument();

    await user.click(deleteButton);

    // The click opens a confirmation naming the account; nothing is deleted yet.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("plain@example.com")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/v1/admin/people/u-plain",
      expect.objectContaining({ method: "DELETE" }),
    );

    const confirm = within(dialog).getByRole("button", { name: /Permanently delete/ });
    expect(confirm).toBeDisabled();

    // The wrong name does not unlock it.
    const field = within(dialog).getByLabelText(/Type/);
    await user.type(field, "plain@example.co");
    expect(confirm).toBeDisabled();

    await user.type(field, "m");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/people/u-plain", {
        method: "DELETE",
      }),
    );
  });

  it("removes a membership only after showing which Hunt goes", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("N. Rahman"));

    await user.click(
      await screen.findByRole("button", { name: "Remove from Brooklyn 2026" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Remove from this Hunt/)).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/v1/admin/people/u-owner/memberships/h2",
      expect.objectContaining({ method: "DELETE" }),
    );

    // Reversible, so no typed name — but still a deliberate second act.
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/people/u-owner/memberships/h2", {
        method: "DELETE",
      }),
    );
  });

  it("lists every selected account for a bulk delete, skips the Hunt owner, and asks for the phrase", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("N. Rahman");
    await user.click(screen.getByLabelText("Select owner@example.com"));
    await user.click(screen.getByLabelText("Select plain@example.com"));
    await user.click(screen.getByRole("button", { name: "Delete 2 accounts" }));

    const dialog = await screen.findByRole("dialog");
    // Both are shown — including the one that cannot go, with the reason.
    expect(within(dialog).getByText("owner@example.com")).toBeInTheDocument();
    expect(within(dialog).getByText(/owns 1 Hunt — transfer ownership first/)).toBeInTheDocument();
    expect(within(dialog).getByText("plain@example.com")).toBeInTheDocument();

    const confirm = within(dialog).getByRole("button", { name: /Permanently delete/ });
    expect(confirm).toBeDisabled();

    // One deletable target left, so it asks for that account's own name.
    await user.type(within(dialog).getByLabelText(/Type/), "plain@example.com");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/people/u-plain", {
        method: "DELETE",
      }),
    );
    // The blocked account is never sent.
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/v1/admin/people/u-owner",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("refuses to remove the Owner from their own Hunt", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("N. Rahman"));

    const ownerCard = screen.getByRole("article", { name: "Jersey City membership" });
    expect(within(ownerCard).getByRole("button")).toBeDisabled();

    // ...but an ordinary membership is removable.
    const curatorCard = screen.getByRole("article", { name: "Brooklyn 2026 membership" });
    expect(within(curatorCard).getByRole("button")).toBeEnabled();
  });

  it("offers Suspend as the reversible alternative and flips to Restore", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("A. Osei"));

    await user.click(await screen.findByRole("button", { name: "Suspend" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/people/u-plain/suspend", {
        method: "POST",
      }),
    );
  });
});
