import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mutations = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("../../auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: "u1" } } }),
}));

vi.mock("./api", () => ({
  useComments: () => ({
    data: [
      {
        id: "c1",
        hunt_listing_id: "l1",
        unit_group_key: "2-1",
        user_id: "u1",
        body: "Worth touring",
        created_at: "2026-07-11T00:00:00Z",
        edited_at: "2026-07-12T00:00:00Z",
        deleted_at: null,
      },
    ],
  }),
  useCreateComment: () => ({ mutate: mutations.create, isPending: false }),
  useUpdateComment: () => ({ mutate: mutations.update, isPending: false }),
  useDeleteComment: () => ({ mutate: mutations.remove }),
}));

import { CommentsSection } from "./CommentsSection";

const members = [
  {
    hunt_id: "h1",
    user_id: "u1",
    role: "member" as const,
    color: "moss",
    display_name: "Yusuf",
  },
];

function renderSection() {
  return render(
    <MantineProvider>
      <CommentsSection
        listingId="l1"
        members={members}
        currentUnitGroup={{ key: "2-1", label: "2 bd / 1 ba" }}
      />
    </MantineProvider>,
  );
}

describe("CommentsSection", () => {
  it("indicates Unit Group scope and edit history", () => {
    renderSection();
    expect(screen.getByText("Yusuf")).toBeInTheDocument();
    expect(screen.getByText("Worth touring")).toBeInTheDocument();
    expect(screen.getByText("2 bd / 1 ba")).toBeInTheDocument();
    expect(screen.getByText(/edited/)).toBeInTheDocument();
  });

  it("lets the author edit a comment", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.click(screen.getByRole("button", { name: "comment actions" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
    const editor = screen.getByRole("textbox", { name: "Edit comment" });
    await user.clear(editor);
    await user.type(editor, "Booked a tour");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(mutations.update).toHaveBeenCalledWith(
      { commentId: "c1", body: "Booked a tour" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("can scope a new comment to the current Unit Group", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.type(screen.getByRole("textbox", { name: "Add a comment" }), "Layout works");
    await user.click(
      screen.getByRole("checkbox", { name: "Only for Current Unit Group: 2 bd / 1 ba" }),
    );
    await user.click(screen.getByRole("button", { name: "Comment" }));
    expect(mutations.create).toHaveBeenCalledWith(
      { body: "Layout works", unit_group_key: "2-1" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});
