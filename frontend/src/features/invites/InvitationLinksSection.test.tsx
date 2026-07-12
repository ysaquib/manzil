import { MantineProvider } from "@mantine/core";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createMutate = vi.fn();
const patchMutate = vi.fn();
const deleteMutate = vi.fn();
const writeText = vi.fn();

const activeLink = {
  id: "link-1",
  hunt_id: "h1",
  created_at: "2026-07-01T00:00:00.000Z",
  name: "Family link",
  max_uses: null,
  expires_at: "2026-07-20T23:59:59.999Z",
  use_count: 0,
  status: "active" as const,
  link: "http://api.example/join/token-1",
  joins: [],
};

const inactiveLink = {
  ...activeLink,
  id: "link-2",
  name: "Old link",
  status: "expired" as const,
  expires_at: "2026-06-01T23:59:59.999Z",
};

vi.mock("./api", () => ({
  invitationLinkForCurrentOrigin: (link: string) =>
    link.replace("http://api.example", "http://localhost"),
  useInvitationLinks: () => ({ data: [activeLink, inactiveLink] }),
  useCreateInvitationLink: () => ({ mutate: createMutate, isPending: false }),
  usePatchInvitationLink: () => ({ mutate: patchMutate, isPending: false }),
  useDeleteInvitationLink: () => ({ mutate: deleteMutate, isPending: false }),
}));

import { InvitationLinksSection } from "./InvitationLinksSection";

function renderSection() {
  return render(
    <MantineProvider>
      <InvitationLinksSection huntId="h1" />
    </MantineProvider>,
  );
}

describe("InvitationLinksSection", () => {
  beforeEach(() => {
    createMutate.mockReset();
    patchMutate.mockReset();
    deleteMutate.mockReset();
    writeText.mockReset();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  it("keeps create fields hidden until the subtle button opens the modal", async () => {
    renderSection();

    expect(screen.queryByRole("button", { name: "Create and copy link" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create invitation link" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Invitation Link 2");
    expect(within(dialog).getByRole("button", { name: "Create and copy link" })).toBeInTheDocument();
  });

  it("defaults the name from active links only and creates with trimmed values", async () => {
    createMutate.mockImplementation(
      (_body: unknown, opts?: { onSuccess?: (link: typeof activeLink) => void }) => {
        opts?.onSuccess?.({
          ...activeLink,
          id: "link-3",
          name: "Weekend guests",
          link: "http://api.example/join/token-3",
        });
      },
    );

    renderSection();
    fireEvent.click(screen.getByRole("button", { name: "Create invitation link" }));

    const dialog = await screen.findByRole("dialog");
    const nameInput = within(dialog).getByLabelText("Name");
    expect(nameInput).toHaveValue("Invitation Link 2");

    fireEvent.change(nameInput, { target: { value: "  Weekend guests  " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create and copy link" }));

    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Weekend guests",
        max_uses: null,
        expires_at: expect.any(String),
      }),
      expect.any(Object),
    );
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(writeText).toHaveBeenCalledWith("http://localhost/join/token-3");
  });

  it("renders link names and can clear a name on edit", () => {
    patchMutate.mockImplementation((_args: unknown, opts?: { onSuccess?: () => void }) => {
      opts?.onSuccess?.();
    });

    renderSection();

    expect(screen.getByText("Family link")).toBeInTheDocument();
    expect(screen.getByText("Old link")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    const nameInput = screen.getByLabelText("Name");
    fireEvent.change(nameInput, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(patchMutate).toHaveBeenCalledWith(
      {
        id: "link-1",
        body: expect.objectContaining({ name: null }),
      },
      expect.any(Object),
    );
  });
});
