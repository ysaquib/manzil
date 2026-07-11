import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: "u1" } } }),
}));

vi.mock("./api", () => ({
  useComments: () => ({
    data: [
      {
        id: "c1",
        hunt_listing_id: "l1",
        user_id: "u1",
        body: "Worth touring",
        created_at: "2026-07-11T00:00:00Z",
        deleted_at: null,
      },
    ],
  }),
  useCreateComment: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteComment: () => ({ mutate: vi.fn() }),
}));

import { CommentsSection } from "./CommentsSection";

describe("CommentsSection", () => {
  it("renders member identity, comment body, and own-delete control", () => {
    render(
      <MantineProvider>
        <CommentsSection
          listingId="l1"
          members={[
            {
              hunt_id: "h1",
              user_id: "u1",
              role: "member",
              color: "moss",
              display_name: "Yusuf",
            },
          ]}
        />
      </MantineProvider>,
    );
    expect(screen.getByText("Yusuf")).toBeInTheDocument();
    expect(screen.getByText("Worth touring")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "delete comment" })).toBeInTheDocument();
  });
});
