// The Hunt picker exists to *not* ask for the Hunt table. These tests are
// mostly about the request that must not happen.
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class extends Error {},
}));

import { HuntPicker } from "../src/features/admin/HuntPicker";

const optionCalls = () =>
  apiFetch.mock.calls.filter((call) => String(call[0]).includes("/hunts/options"));

describe("HuntPicker", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue([
      { hunt_id: "h1", name: "Brooklyn 2026", owner_name: "N. Rahman" },
    ]);
  });

  it("asks for nothing when it is opened", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HuntPicker value={null} onChange={() => {}} />);

    await user.click(screen.getByRole("combobox"));

    expect(await screen.findByText("Type 3 characters to search")).toBeInTheDocument();
    expect(optionCalls()).toHaveLength(0);
  });

  it("stays quiet below three characters", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HuntPicker value={null} onChange={() => {}} />);

    await user.type(screen.getByRole("combobox"), "br");

    // Long enough for the 250ms debounce to have fired if it were going to.
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(optionCalls()).toHaveLength(0);
  });

  it("searches at three characters and offers what the server matched", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(<HuntPicker value={null} onChange={onChange} />);

    await user.type(screen.getByRole("combobox"), "bro");

    await waitFor(() => expect(optionCalls()).toHaveLength(1));
    expect(optionCalls()[0][0]).toBe("/v1/admin/hunts/options?q=bro");

    // The owner is part of the label because two Hunts often share a name.
    await user.click(await screen.findByText("Brooklyn 2026 — N. Rahman"));
    expect(onChange).toHaveBeenCalledWith("h1", "Brooklyn 2026 — N. Rahman");
  });
});
