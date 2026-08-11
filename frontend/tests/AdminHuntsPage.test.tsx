// AD-4: the Hunt table is paged and searched by the server.
//
// The property under test is what the page *asks for*. Filtering a
// roll-up-carrying route in the browser means fetching the whole installation
// first, which is the thing this replaced — so the assertions are on the query
// string, not just on what ends up rendered.
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

import { AdminHuntsPage } from "../src/features/admin/AdminHuntsPage";

function hunt(id: string, name: string) {
  return {
    hunt_id: id,
    name,
    owner_id: "u1",
    owner_name: "N. Rahman",
    members: 2,
    listings: 4,
    jobs: 9,
    llm_cost_usd: 1.5,
    fetch_cost_usd: 0.25,
    total_cost_usd: 1.75,
    created_at: "2026-07-01T00:00:00Z",
    last_activity_at: null,
  };
}

/** 120 Hunts on the server; the route only ever hands back a page. */
const ALL = Array.from({ length: 120 }, (_, i) => hunt(`h${i + 1}`, `Hunt ${i + 1}`));
let deletionBlockers: string[] = [];

function management(huntId: string) {
  const selected = ALL.find((row) => row.hunt_id === huntId)!;
  return {
    hunt_id: huntId,
    name: selected.name,
    owner_id: "u1",
    owner_name: "N. Rahman",
    caller_is_member: false,
    members: [
      { user_id: "u1", display_name: "N. Rahman", role: "owner" },
      { user_id: "u2", display_name: "Sam Lee", role: "member" },
    ],
    deletion_blockers: deletionBlockers,
  };
}

const listCalls = () =>
  apiFetch.mock.calls
    .map((call) => String(call[0]))
    .filter((path) => path.startsWith("/v1/admin/hunts?"));

function renderPage() {
  return renderWithProviders(
    <MemoryRouter>
      <AdminHuntsPage />
    </MemoryRouter>,
  );
}

describe("AdminHuntsPage", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    deletionBlockers = [];
    apiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/v1/admin/hunts?")) {
        const params = new URLSearchParams(path.split("?")[1]);
        const search = params.get("search");
        const limit = Number(params.get("limit"));
        const offset = Number(params.get("offset"));
        const matched = search
          ? ALL.filter((h) => h.name.toLowerCase().includes(search.toLowerCase()))
          : ALL;
        return Promise.resolve({
          items: matched.slice(offset, offset + limit),
          total: matched.length,
        });
      }
      const managementMatch = path.match(/^\/v1\/admin\/hunts\/(h\d+)\/management$/);
      if (managementMatch) return Promise.resolve(management(managementMatch[1]!));
      if (path.endsWith("/activity")) return Promise.resolve([]);
      if (path.endsWith("/transfer-ownership")) return Promise.resolve({ status: "ok" });
      if (/^\/v1\/admin\/hunts\/h\d+$/.test(path)) {
        return Promise.resolve({ hunt_id: path.split("/").at(-1), name: "Hunt 1" });
      }
      return Promise.resolve([]);
    });
  });

  it("asks for one page and reports the server's total", async () => {
    renderPage();

    expect(await screen.findByText("Hunt 1")).toBeInTheDocument();
    expect(screen.queryByText("Hunt 51")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1–50 of 120 Hunts")).toBeInTheDocument();
    expect(listCalls()[0]).toBe("/v1/admin/hunts?limit=50&offset=0");
  });

  it("fetches the next page rather than slicing one it already has", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Hunt 1");

    await user.click(screen.getByRole("button", { name: "3" }));

    await waitFor(() => expect(screen.getByText("Hunt 101")).toBeInTheDocument());
    expect(listCalls()).toContain("/v1/admin/hunts?limit=50&offset=100");
    expect(screen.getByText("Showing 101–120 of 120 Hunts")).toBeInTheDocument();
  });

  it("sends the search to the server and returns to page 1", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Hunt 1");

    await user.click(screen.getByRole("button", { name: "3" }));
    await waitFor(() => expect(screen.getByText("Hunt 101")).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText("Search Hunt or owner…"), "Hunt 11");

    // Page 3 of the old list does not exist in the new one; staying there would
    // show an empty table and blame the search.
    await waitFor(() =>
      expect(listCalls()).toContain("/v1/admin/hunts?limit=50&offset=0&search=Hunt+11"),
    );
    await waitFor(() => expect(screen.getByText("Hunt 11")).toBeInTheDocument());
    expect(screen.getByText(/Showing 1–\d+ of 11 Hunts/)).toBeInTheDocument();
  });

  it("transfers ownership to an existing Hunt member from the detail panel", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Hunt 1"));
    const ownerPicker = await screen.findByRole("combobox", { name: "New Owner" });
    await waitFor(() =>
      expect(ownerPicker).toHaveAttribute("placeholder", "Choose an existing member"),
    );
    await user.click(ownerPicker);
    await user.click(await screen.findByRole("option", { name: "Sam Lee", hidden: true }));
    await user.click(screen.getByRole("button", { name: "Transfer ownership" }));

    const dialog = await screen.findByRole("dialog", { name: "Transfer Hunt ownership?" });
    expect(dialog).toHaveTextContent("Sam Lee becomes the Owner");
    await user.click(within(dialog).getByRole("button", { name: "Transfer ownership" }));

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/hunts/h1/transfer-ownership", {
        method: "POST",
        body: { new_owner_id: "u2" },
      }),
    );
  });

  it("permanently deletes a Hunt only after its exact name is typed", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Hunt 1"));
    await user.click(await screen.findByRole("button", { name: "Delete Hunt permanently" }));

    const dialog = await screen.findByRole("dialog", { name: "Delete this Hunt permanently?" });
    expect(within(dialog).getByText(/Shared Properties, Sources/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Permanently delete Hunt" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Type/), "Hunt 1");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/v1/admin/hunts/h1", {
        method: "DELETE",
        body: { confirmation_name: "Hunt 1" },
      }),
    );
  });

  it("names a Hunt deletion blocker and never sends the delete", async () => {
    deletionBlockers = ["1 active Job must finish or be cancelled first"];
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Hunt 1"));
    expect(await screen.findByText(deletionBlockers[0]!)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete Hunt permanently" }));

    const dialog = await screen.findByRole("dialog", { name: "Delete this Hunt permanently?" });
    expect(within(dialog).getByText(/Skipped/)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Permanently delete Hunt" }),
    ).toBeDisabled();
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/v1/admin/hunts/h1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
