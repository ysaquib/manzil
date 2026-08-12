import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

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

import { BuildVersionPopover } from "../src/components/BuildVersionPopover";

describe("BuildVersionPopover", () => {
  it("shows both artifacts and quietly explains a deploy mismatch", async () => {
    const user = userEvent.setup();
    renderWithProviders(<BuildVersionPopover />);

    await user.click(screen.getByRole("button", { name: /frontend release 0\.1\.0/i }));

    expect(await screen.findByText("build aaaaaaa1111111")).toBeInTheDocument();
    expect(screen.getByText("build bbbbbbb2222222")).toBeInTheDocument();
    expect(screen.getByText(/Different deploys/)).toBeInTheDocument();
  });
});
