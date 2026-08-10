import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const hooks = vi.hoisted(() => ({
  status: vi.fn(),
  hunts: vi.fn(),
  preflight: vi.fn(),
  publish: vi.fn(),
  toggle: vi.fn(),
}));

vi.mock("../src/features/admin/api", () => ({
  useAdminDemoStatus: hooks.status,
  useDemoHuntOptions: hooks.hunts,
  useDemoPreflight: hooks.preflight,
  usePublishDemo: hooks.publish,
  useToggleDemo: hooks.toggle,
}));

import { AdminDemoPage } from "../src/features/admin/AdminDemoPage";

const current = {
  enabled: false,
  available: false,
  hunt_id: "hunt-1",
  hunt_name: "Public showcase",
  owned_by_caller: true,
  release_id: "release-1",
  release_state: "ready",
  published_at: "2026-08-10T12:00:00Z",
  active_count: 3,
  replay_count: 2,
  mapped_count: 5,
  warnings: [],
  blockers: [],
  stale: false,
  freshness_error: null,
  updated_at: "2026-08-10T12:00:00Z",
  publication: null,
};

describe("AdminDemoPage", () => {
  const toggleMutate = vi.fn();

  beforeEach(() => {
    hooks.status.mockReturnValue({ data: current, isPending: false, isError: false });
    hooks.hunts.mockReturnValue({ data: [], isPending: false });
    hooks.preflight.mockReturnValue({ mutate: vi.fn(), isPending: false });
    hooks.publish.mockReturnValue({ mutate: vi.fn(), isPending: false });
    hooks.toggle.mockReturnValue({ mutate: toggleMutate, isPending: false });
    toggleMutate.mockReset();
  });

  it("reenables a retained current release without republishing", async () => {
    renderWithProviders(<AdminDemoPage />);

    expect(screen.getByText("Public showcase")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Enable Demo Mode" }));
    expect(toggleMutate).toHaveBeenCalledWith(true, expect.any(Object));
  });

  it("shows explicit publication when derived inputs are stale", () => {
    hooks.status.mockReturnValue({
      data: { ...current, stale: true },
      isPending: false,
      isError: false,
    });
    renderWithProviders(<AdminDemoPage />);

    expect(screen.queryByRole("button", { name: "Enable Demo Mode" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish updates" })).toBeInTheDocument();
    expect(screen.getByText("Replay or map inputs changed")).toBeInTheDocument();
  });

  it("does not label a configured-but-ineligible release as public", () => {
    hooks.status.mockReturnValue({
      data: {
        ...current,
        enabled: true,
        available: false,
        blockers: ["the release is no longer owner-consented"],
      },
      isPending: false,
      isError: false,
    });
    renderWithProviders(<AdminDemoPage />);

    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("Demo access is blocked")).toBeInTheDocument();
    expect(screen.queryByText("Public")).not.toBeInTheDocument();
  });
});
