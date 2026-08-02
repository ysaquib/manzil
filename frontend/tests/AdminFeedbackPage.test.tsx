// AD-2: the inbox card. What is asserted here is that the context which makes a
// two-line report reproducible — the route with its drawer params, the build,
// the browser — is on the card rather than behind a click, and that triage is
// one action rather than a form.
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class extends Error {},
}));

import { AdminFeedbackPage } from "../src/features/admin/AdminFeedbackPage";

const REPORT = {
  id: "r1",
  category: "wrong_data",
  body: "The all-in price double-counts the amenity fee.",
  route: "/h/abc/overview?drawer=listing&id=9f31c2",
  hunt_id: "h1",
  hunt_name: "Brooklyn 2026",
  app_version: "2.0.108",
  user_agent: "Safari 18.4",
  reporter_id: "u1",
  reporter_name: "N. Rahman",
  reporter_email: "n@example.com",
  triage: "new",
  triaged_at: null,
  created_at: "2026-08-01T09:12:00Z",
};

function route(path: string) {
  if (path.startsWith("/v1/admin/feedback/counts")) {
    return Promise.resolve({ new: 1, seen: 0, actioned: 0, wont_fix: 0 });
  }
  if (path.startsWith("/v1/admin/feedback")) {
    return Promise.resolve([REPORT]);
  }
  return Promise.resolve({});
}

describe("AdminFeedbackPage", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockImplementation((path: string) => route(path));
  });

  it("shows the reproduction context on the card, not behind a click", async () => {
    renderWithProviders(
      <MemoryRouter>
        <AdminFeedbackPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText(/double-counts the amenity fee/)).toBeInTheDocument();
    expect(screen.getByText("N. Rahman")).toBeInTheDocument();
    // Route, build and browser on one line — the drawer params are the whole
    // point, since that is what identifies the Listing being complained about.
    expect(
      screen.getByText(/drawer=listing&id=9f31c2 · 2\.0\.108 · Safari 18\.4/),
    ).toBeInTheDocument();
  });

  it("opens on New, because an inbox that opens on everything is not an inbox", async () => {
    renderWithProviders(
      <MemoryRouter>
        <AdminFeedbackPage />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/feedback?triage=new"),
    );
  });

  it("triages in one click and never offers the state it is already in", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <AdminFeedbackPage />
      </MemoryRouter>,
    );

    await screen.findByText(/double-counts/);
    await user.click(screen.getByText("New", { selector: ".mantine-Badge-root, .mantine-Badge-label" }));

    const actioned = await screen.findByRole("menuitem", { name: "Actioned" });
    await user.click(actioned);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/feedback/r1", {
        method: "PATCH",
        body: { triage: "actioned" },
      }),
    );
  });

  it("says nothing is waiting rather than showing an empty page", async () => {
    apiFetch.mockImplementation((path: string) =>
      path.startsWith("/v1/admin/feedback/counts")
        ? Promise.resolve({ new: 0, seen: 0, actioned: 0, wont_fix: 0 })
        : Promise.resolve([]),
    );

    renderWithProviders(
      <MemoryRouter>
        <AdminFeedbackPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/Everything submitted has been looked at/),
    ).toBeInTheDocument();
  });
});
