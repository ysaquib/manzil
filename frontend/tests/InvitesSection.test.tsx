import { MantineProvider } from "@mantine/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("@mantine/notifications", () => ({ notifications: { show: notify } }));

type MutateOptions = { onSuccess?: () => void; onError?: (error: unknown) => void };
const createMutate = vi.fn((_body: unknown, opts?: MutateOptions) => opts?.onSuccess?.());
const revokeMutate = vi.fn();

const PENDING = {
  id: "inv-1",
  email: "partner@example.com",
  role_granted: "member" as const,
  expires_at: "2026-08-20T00:00:00.000Z",
  link: "http://api.example/invite/tok-1",
};

vi.mock("../src/features/invites/api", () => ({
  invitationLinkForCurrentOrigin: (link: string) =>
    link.replace("http://api.example", "http://localhost"),
  useInvites: () => ({ data: [PENDING] }),
  useCreateInvite: () => ({ mutate: createMutate, isPending: false }),
  useRevokeInvite: () => ({ mutate: revokeMutate, isPending: false }),
}));

import { ApiError } from "../src/lib/apiClient";
import { InvitesSection } from "../src/features/invites/InvitesSection";

function renderSection() {
  return render(
    <MantineProvider>
      <InvitesSection huntId="h1" />
    </MantineProvider>,
  );
}

describe("InvitesSection", () => {
  beforeEach(() => {
    notify.mockReset();
    createMutate.mockReset();
    createMutate.mockImplementation((_body: unknown, opts?: MutateOptions) =>
      opts?.onSuccess?.(),
    );
    revokeMutate.mockReset();
  });

  it("requires an email and sends a single-recipient invite", async () => {
    const user = userEvent.setup();
    renderSection();

    const send = screen.getByRole("button", { name: "Send invite" });
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Email" }), "partner@example.com");
    await user.click(send);

    expect(createMutate).toHaveBeenCalledWith(
      { email: "partner@example.com", role: "member" },
      expect.any(Object),
    );
  });

  // The email goes out through Supabase Auth, which refuses an address with no
  // account — so the row exists and the mail does not. Reporting that as
  // "couldn't create invite" sends the Owner to make a second one.
  it("says the invite was created when only its email failed, and keeps the link reachable", async () => {
    createMutate.mockImplementation((_body: unknown, opts?: MutateOptions) =>
      opts?.onError?.(new ApiError(502, "invite_email_failed", "mail refused")),
    );
    const user = userEvent.setup();
    renderSection();

    const field = screen.getByRole("textbox", { name: "Email" });
    await user.type(field, "stranger@example.com");
    await user.click(screen.getByRole("button", { name: "Send invite" }));

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Invite created, but the email wasn't sent",
        color: "yellow",
      }),
    );
    expect(field).toHaveValue("");
    // The Owner's fallback: send it themselves.
    expect(
      screen.getByRole("button", { name: "Copy invite link for partner@example.com" }),
    ).toBeInTheDocument();
  });

  it("confirms before revoking a pending invite", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "revoke invite" }));
    expect(revokeMutate).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("partner@example.com")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Revoke invite" }));

    expect(revokeMutate).toHaveBeenCalledWith("inv-1", expect.any(Object));
  });
});
