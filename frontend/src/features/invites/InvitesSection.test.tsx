import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const createMutate = vi.fn(
  (_body: unknown, opts?: { onSuccess?: (invite: { link: string }) => void }) =>
    opts?.onSuccess?.({ link: "https://manzil.app/invite/tok-123" }),
);

vi.mock("./api", () => ({
  useInvites: () => ({ data: [] }),
  useCreateInvite: () => ({ mutate: createMutate, isPending: false }),
  useRevokeInvite: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { InvitesSection } from "./InvitesSection";

describe("InvitesSection", () => {
  it("reveals the returned invite link after a successful create", async () => {
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <InvitesSection huntId="h1" />
      </MantineProvider>,
    );

    // No link before creating.
    expect(screen.queryByDisplayValue("https://manzil.app/invite/tok-123")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create invite" }));

    expect(createMutate).toHaveBeenCalled();
    expect(screen.getByDisplayValue("https://manzil.app/invite/tok-123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });
});
