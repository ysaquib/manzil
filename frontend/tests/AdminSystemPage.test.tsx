import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

vi.mock("../src/features/admin/api", () => ({
  useSystem: () => ({
    isPending: false,
    data: {
      queued: 0,
      running: 0,
      stale_locks: 0,
      oldest_queued_seconds: 0,
      worker_status: "live_idle",
      live_workers: 1,
      busy_workers: 0,
      last_heartbeat: "2026-08-11T12:00:00Z",
      finished_24h: 2,
      failed_24h: 0,
      last_migration: "20260901000021",
      model_pins: [],
      services: [],
      priced_models: 3,
      mode: "workflow",
    },
  }),
}));

vi.mock("../src/lib/buildInfo", async () => {
  const actual = await vi.importActual<typeof import("../src/lib/buildInfo")>(
    "../src/lib/buildInfo",
  );
  return {
    ...actual,
    frontendBuildInfo: {
      service: "frontend",
      release_version: "0.1.0",
      build_sha: "aaaaaaa1111111",
      build_id: "0.1.0+aaaaaaa",
      environment: "production",
    },
    useApiBuildInfo: () => ({
      data: {
        service: "api",
        release_version: "0.1.0",
        build_sha: "bbbbbbb2222222",
        build_id: "0.1.0+bbbbbbb",
        environment: "production",
      },
    }),
  };
});

import { AdminSystemPage } from "../src/features/admin/AdminSystemPage";

describe("AdminSystemPage", () => {
  it("shows both full build SHAs and makes a mismatch explicit", () => {
    renderWithProviders(<MemoryRouter><AdminSystemPage /></MemoryRouter>);

    expect(screen.getByText("build aaaaaaa1111111")).toBeInTheDocument();
    expect(screen.getByText("build bbbbbbb2222222")).toBeInTheDocument();
    expect(screen.getByText("Frontend and API are different deploys")).toBeInTheDocument();
  });
});
