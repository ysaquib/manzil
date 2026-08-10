import { MantineProvider } from "@mantine/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const createMutate = vi.fn((_body: unknown, opts?: { onSuccess?: () => void }) =>
  opts?.onSuccess?.(),
);
const revokeMutate = vi.fn();

const PENDING = {
  id: "inv-1",
  email: "partner@example.com",
  role_granted: "member" as const,
  expires_at: "2026-08-20T00:00:00.000Z",
};

vi.mock("../src/features/invites/api", () => ({
  useInvites: () => ({ data: [PENDING] }),
  useCreateInvite: () => ({ mutate: createMutate, isPending: false }),
  useRevokeInvite: () => ({ mutate: revokeMutate, isPending: false }),
}));

import { InvitesSection } from "../src/features/invites/InvitesSection";

describe("InvitesSection", () => {
  it("requires an email and sends a single-recipient invite", async () => {
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <InvitesSection huntId="h1" />
      </MantineProvider>,
    );

    const send = screen.getByRole("button", { name: "Send invite" });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Email" }), "partner@example.com");
    await user.click(send);

    expect(createMutate).toHaveBeenCalledWith(
      { email: "partner@example.com", role: "member" },
      expect.any(Object),
    );
  });

  it("confirms before revoking a pending invite", async () => {
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <InvitesSection huntId="h1" />
      </MantineProvider>,
    );

    await user.click(screen.getByRole("button", { name: "revoke invite" }));
    expect(revokeMutate).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("partner@example.com")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Revoke invite" }));

    expect(revokeMutate).toHaveBeenCalledWith("inv-1", expect.any(Object));
  });
});
