import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";
import { ColorSchemeToggle } from "../src/components/ColorSchemeToggle";

const setColorScheme = vi.fn();

vi.mock("@mantine/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mantine/core")>();
  return {
    ...actual,
    useMantineColorScheme: () => ({ setColorScheme, colorScheme: "auto" }),
    useComputedColorScheme: () => "light",
  };
});

describe("ColorSchemeToggle", () => {
  it("toggles to dark when the computed scheme is light", async () => {
    renderWithProviders(<ColorSchemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Toggle color scheme" }));
    expect(setColorScheme).toHaveBeenCalledWith("dark");
  });
});
