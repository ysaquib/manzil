// The creation stepper's contract is what it writes, not what it renders: a
// hunt accepting every default must cost exactly one request, and only the
// fields a person actually changed may be persisted — an explicit write of a
// default would freeze the hunt against later default changes.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
const useAuth = vi.hoisted(() => vi.fn());
const useProfile = vi.hoisted(() => vi.fn());

vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class ApiError extends Error {},
}));
vi.mock("../src/auth/useAuth", () => ({ useAuth }));
vi.mock("../src/auth/profile", () => ({ useProfile }));

import { CreateHuntModal } from "../src/features/hunts/CreateHuntModal";

function renderModal() {
  return renderWithProviders(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<CreateHuntModal opened onClose={() => {}} />} />
        <Route path="/h/:huntId" element={<div>Hunt overview</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

const next = () => screen.getByRole("button", { name: /^next$/i });

describe("CreateHuntModal", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockImplementation((path: string) =>
      path === "/v1/hunts" ? Promise.resolve({ id: "hunt-9" }) : Promise.resolve({}),
    );
    useAuth.mockReturnValue({ session: { user: { id: "user-1" } }, loading: false });
    useProfile.mockReturnValue({
      data: { user_id: "user-1", default_display_name: "Yusuf", default_color: "dusky" },
      isLoading: false,
    });
  });

  it("writes only the hunt when every default is accepted", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText(/hunt name/i), "Detroit 2026");
    await user.click(next()); // Household
    await user.click(next()); // Defaults
    await user.click(next()); // Appearance
    await user.click(next()); // Review
    await user.click(screen.getByRole("button", { name: /create hunt/i }));

    expect(await screen.findByText("Hunt overview")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith("/v1/hunts", {
      method: "POST",
      body: { name: "Detroit 2026", domain: "rent" },
    });
  });

  it("persists household, defaults, and appearance only where they were changed", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText(/hunt name/i), "Detroit");
    await user.click(next());

    const people = screen.getByLabelText("People");
    await user.clear(people);
    await user.type(people, "2");
    await user.click(next());

    await user.click(screen.getByRole("radio", { name: /median month/i }));
    await user.click(next());

    const displayName = screen.getByLabelText(/display name/i);
    await user.clear(displayName);
    await user.type(displayName, "Yus");
    await user.click(next());

    await user.click(screen.getByRole("button", { name: /create hunt/i }));
    expect(await screen.findByText("Hunt overview")).toBeInTheDocument();

    const paths = apiFetch.mock.calls.map((call) => call[0] as string);
    expect(paths).toEqual([
      "/v1/hunts",
      "/v1/hunts/hunt-9/settings",
      "/v1/hunts/hunt-9/members/user-1",
    ]);
    // Occupants and the cost mode carry the edits; the untouched proximity
    // mode still rides along, because settings PATCH takes the whole object.
    expect(apiFetch.mock.calls[1]?.[1]).toMatchObject({
      method: "PATCH",
      body: {
        settings: {
          occupants: 2,
          cats: 0,
          dogs: 0,
          cost_estimate_mode: "median",
          proximity_mode: "driving",
        },
      },
    });
    // Only the name changed, so no second member PATCH for the color.
    expect(apiFetch.mock.calls[2]?.[1]).toMatchObject({
      method: "PATCH",
      body: { display_name: "Yus" },
    });
  });

  it("offers the full member palette, not the six-token invite subset", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText(/hunt name/i), "Palette");
    await user.click(next());
    await user.click(next());
    await user.click(next());

    const palette = screen.getByRole("radiogroup", { name: /your color/i });
    // Thirteen theme tokens plus the custom-picker swatch.
    expect(within(palette).getAllByRole("radio")).toHaveLength(14);
    expect(within(palette).getByRole("radio", { name: "teal" })).toBeInTheDocument();
    expect(within(palette).getByRole("radio", { name: "indigo" })).toBeInTheDocument();
  });

  it("summarizes the draft on Review and jumps back to the step that owns a value", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByLabelText(/hunt name/i), "Corktown");
    await user.click(next());
    await user.click(next());
    await user.click(next());
    await user.click(next());

    expect(screen.getByText("Corktown")).toBeInTheDocument();
    expect(screen.getByText("1 person")).toBeInTheDocument();
    expect(screen.getByText("no pets")).toBeInTheDocument();
    expect(screen.getByText("Conservative")).toBeInTheDocument();
    expect(screen.getByText("Yusuf")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /edit household/i }));
    expect(screen.getByLabelText("People")).toBeInTheDocument();
  });

  it("keeps Next disabled until the hunt has a name", async () => {
    const user = userEvent.setup();
    renderModal();

    expect(next()).toBeDisabled();
    await user.type(screen.getByLabelText(/hunt name/i), "   ");
    expect(next()).toBeDisabled();

    await user.type(screen.getByLabelText(/hunt name/i), "Midtown");
    expect(next()).toBeEnabled();
  });
});
