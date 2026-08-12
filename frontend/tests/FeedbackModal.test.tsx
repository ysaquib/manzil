// Feedback submission (P3-16). The context strip is the reason this surface
// earns its keep, so what actually travels with the report is asserted.
import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const submitMutate = vi.fn(
  (_draft: unknown, opts?: { onSuccess?: (receipt: unknown) => void }) =>
    opts?.onSuccess?.({ id: "fb_1", created_at: "2026-07-29T00:00:00Z" }),
);

vi.mock("../src/features/feedback/api", async () => {
  const actual = await vi.importActual<typeof import("../src/features/feedback/api")>(
    "../src/features/feedback/api",
  );
  return {
    ...actual,
    appVersion: () => "v3.27",
    useSubmitFeedback: () => ({ mutate: submitMutate, isPending: false }),
  };
});

vi.mock("../src/lib/buildInfo", async () => {
  const actual = await vi.importActual<typeof import("../src/lib/buildInfo")>(
    "../src/lib/buildInfo",
  );
  return {
    ...actual,
    useApiBuildInfo: () => ({
      data: {
        service: "api",
        release_version: "0.1.0",
        build_sha: "def5678999999",
        build_id: "0.1.0+def5678",
        environment: "production",
      },
    }),
  };
});

vi.mock("../src/auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: "u1", email: "yusuf@example.com" } } }),
}));

import { FeedbackModal } from "../src/features/feedback/FeedbackModal";

function renderModal(route = "/h/hunt-1?listing=lst_8f21") {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route
            path="/h/:huntId"
            element={<FeedbackModal opened onClose={() => {}} />}
          />
        </Routes>
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe("FeedbackModal", () => {
  it("sends the category, body, and the context the reader can see", async () => {
    const user = userEvent.setup();
    renderModal();

    // The strip shows exactly what will be sent.
    expect(screen.getByText("/h/hunt-1?listing=lst_8f21")).toBeInTheDocument();
    expect(screen.getByText("· frontend v3.27 · api 0.1.0+def5678")).toBeInTheDocument();
    expect(screen.getByText("· yusuf@example.com")).toBeInTheDocument();

    await user.click(screen.getByText("Feature request"));
    await user.type(
      screen.getByRole("textbox", { name: /Tell us what happened/ }),
      "  Sort by commute time  ",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    expect(submitMutate).toHaveBeenCalledWith(
      {
        category: "feature",
        body: "Sort by commute time",
        route: "/h/hunt-1?listing=lst_8f21",
        hunt_id: "hunt-1",
        app_version: "frontend v3.27 · api 0.1.0+def5678",
      },
      expect.anything(),
    );
  });

  it("cannot send an empty report", async () => {
    renderModal();
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeDisabled();
  });

  it("defaults to Bug", async () => {
    renderModal();
    expect(screen.getByRole("radio", { name: "Bug" })).toBeChecked();
  });
});
