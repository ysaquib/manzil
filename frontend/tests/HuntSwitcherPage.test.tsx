import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useHunts = vi.hoisted(() => vi.fn());
const useCreateHunt = vi.hoisted(() => vi.fn());
const useAdminIdentity = vi.hoisted(() => vi.fn());

vi.mock("../src/features/hunts/api", () => ({ useHunts, useCreateHunt }));
vi.mock("../src/features/admin/api", () => ({ useAdminIdentity }));
vi.mock("../src/components/UserMenu", () => ({ UserMenu: () => null }));

import { HuntSwitcherPage } from "../src/features/hunts/HuntSwitcherPage";

const HUNTS = [
  {
    id: "mine-1",
    name: "Detroit apartments",
    rubric_version: 3,
  },
];

function renderPage() {
  return renderWithProviders(
    <MemoryRouter>
      <HuntSwitcherPage />
    </MemoryRouter>,
  );
}

describe("HuntSwitcherPage", () => {
  beforeEach(() => {
    useHunts.mockReturnValue({ data: HUNTS, isLoading: false, error: null });
    useCreateHunt.mockReturnValue({ mutate: vi.fn(), isPending: false });
    useAdminIdentity.mockReturnValue({ data: { is_site_admin: false } });
  });

  it("shows the primary admin card above the member's Hunts for a Site Admin", () => {
    useAdminIdentity.mockReturnValue({ data: { is_site_admin: true } });
    renderPage();

    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveAccessibleName(/admin panel/i);
    expect(links[0]).toHaveAttribute("href", "/admin");
    expect(links[0]).toHaveAttribute("data-active", "true");
    expect(links[1]).toHaveAccessibleName(/detroit apartments/i);
    expect(links[1]).toHaveAttribute("href", "/h/mine-1");
  });

  it("does not show the admin card to an ordinary member", () => {
    renderPage();

    expect(screen.queryByRole("link", { name: /admin panel/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /detroit apartments/i })).toBeInTheDocument();
  });
});
