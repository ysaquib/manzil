import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const useHunts = vi.hoisted(() => vi.fn());
const useAdminIdentity = vi.hoisted(() => vi.fn());

vi.mock("../src/features/hunts/api", () => ({ useHunts }));
vi.mock("../src/features/admin/api", () => ({ useAdminIdentity }));
vi.mock("../src/components/UserMenu", () => ({ UserMenu: () => null }));

import { HuntSwitcherPage } from "../src/features/hunts/HuntSwitcherPage";

const HUNTS = [
  {
    id: "mine-1",
    name: "Detroit apartments",
    rubric_version: 3,
    created_at: "2026-07-08T00:00:00Z",
    archived_at: null,
    locked_at: null,
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
    const hunt = screen.getByRole("link", { name: /detroit apartments/i });
    expect(hunt).toBeInTheDocument();
    expect(hunt).toHaveTextContent("Created Wednesday, 08 July, 2026");
    expect(hunt).not.toHaveTextContent(/rubric v/i);
  });

  it("keeps archived Hunts behind one subtle reveal", async () => {
    const user = userEvent.setup();
    useHunts.mockReturnValue({
      data: [
        ...HUNTS,
        {
          ...HUNTS[0],
          id: "archived-1",
          name: "Last year's search",
          archived_at: "2026-08-01T00:00:00Z",
        },
      ],
      isLoading: false,
      error: null,
    });
    renderPage();

    expect(screen.queryByRole("link", { name: /last year's search/i })).not.toBeInTheDocument();
    const reveal = screen.getByRole("button", { name: /show archived \(1\)/i });
    expect(reveal).toHaveAttribute("aria-expanded", "false");
    await user.click(reveal);

    expect(screen.getByRole("link", { name: /last year's search/i })).toHaveAttribute(
      "href",
      "/h/archived-1",
    );
    expect(reveal).toHaveAttribute("aria-expanded", "true");
  });

  it("opens the creation stepper from the header button, starting on Name", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /create new hunt/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/create a new hunt/i)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/hunt name/i)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /^next$/i })).toBeDisabled();
  });
});
