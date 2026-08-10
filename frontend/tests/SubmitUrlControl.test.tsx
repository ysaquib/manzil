// Submitting a listing is the app's most frequent write, and it is one pasted
// field. Enter has to finish it.
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../src/lib/apiClient", () => ({
  apiFetch,
  ApiError: class extends Error {},
}));

import { SubmitUrlControl } from "../src/features/listings/SubmitUrlControl";

const URL = "https://example.com/some-building/1a";

describe("SubmitUrlControl", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({ id: "l1" });
  });

  it("enqueues on Enter from the URL field", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SubmitUrlControl huntId="h1" defaultPolicy="tiers_1_2_3" />);

    await user.type(screen.getByLabelText("Add a listing"), `${URL}{Enter}`);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        "/v1/hunts/h1/listings",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("ignores Enter on an empty field rather than posting a blank URL", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SubmitUrlControl huntId="h1" defaultPolicy="tiers_1_2_3" />);

    await user.type(screen.getByLabelText("Add a listing"), "{Enter}");

    // The control's own reads (ghost-mode identity) are not the point; no
    // listing may be enqueued.
    expect(
      apiFetch.mock.calls.filter((call) => String(call[0]).includes("/listings")),
    ).toHaveLength(0);
  });
});
