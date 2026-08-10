// The admin shell at two widths.
//
// The phone case is the one worth pinning: eight links in two labelled groups
// used to wrap into rows of pills above the content, which lost the grouping and
// ate a third of a phone viewport. It is a Burger and a drawer now, like the
// rest of the app.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class extends Error {},
}));

const matches = vi.hoisted(() => ({ compact: false }));
vi.mock("@mantine/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@mantine/hooks")>()),
  useMediaQuery: () => matches.compact,
}));

import { AdminLayout } from "../src/features/admin/AdminLayout";

function renderAdmin(path = "/admin/people") {
  return renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<div>overview page</div>} />
          <Route path="people" element={<div>people page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminLayout", () => {
  beforeEach(() => {
    matches.compact = false;
    apiFetch.mockReset();
    apiFetch.mockImplementation((path: string) => {
      if (path === "/v1/admin/me") {
        return Promise.resolve({
          user_id: "u1",
          is_site_admin: true,
          is_primordial: true,
          granted_at: null,
        });
      }
      return Promise.resolve({ new: 0, seen: 0, actioned: 0, wont_fix: 0 });
    });
  });

  it("shows the whole rail on a desktop", async () => {
    renderAdmin();

    const rail = await screen.findByRole("navigation", { name: "Admin sections" });
    expect(within(rail).getByText("Operations")).toBeInTheDocument();
    expect(within(rail).getByText("Audit log")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Admin sections" })).not.toBeInTheDocument();
  });

  it("puts the rail behind a Burger on a phone, with the section named in the bar", async () => {
    matches.compact = true;
    renderAdmin();

    // Nothing but the bar until it is asked for — no pill rows over the page.
    expect(await screen.findByText("People")).toBeInTheDocument();
    expect(screen.queryByText("Operations")).not.toBeInTheDocument();

    const burger = screen.getByRole("button", { name: "Admin sections" });
    await userEvent.click(burger);

    const rail = await screen.findByRole("navigation", { name: "Admin sections" });
    // The groups survive the move: the drawer reuses the rail verbatim.
    expect(within(rail).getByText("Operations")).toBeInTheDocument();
    expect(within(rail).getByRole("link", { name: "Audit log" })).toBeInTheDocument();
  });

  it("closes the drawer when a section is chosen", async () => {
    matches.compact = true;
    renderAdmin("/admin");

    await userEvent.click(await screen.findByRole("button", { name: "Admin sections" }));
    const rail = await screen.findByRole("navigation", { name: "Admin sections" });
    await userEvent.click(within(rail).getByRole("link", { name: "People" }));

    expect(await screen.findByText("people page")).toBeInTheDocument();
    // A navigation left open over the page it just opened is worse than none.
    // `waitFor` because the drawer unmounts after its close transition.
    await waitFor(() => expect(screen.queryByText("Operations")).not.toBeInTheDocument());
  });
});
