import { MantineProvider } from "@mantine/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Invite } from "../src/features/invites/api";

const notify = vi.hoisted(() => vi.fn());
vi.mock("@mantine/notifications", () => ({ notifications: { show: notify } }));

type MutateOptions = { onSuccess?: () => void; onError?: (error: unknown) => void };
const createMutate = vi.fn((_body: unknown, opts?: MutateOptions) => opts?.onSuccess?.());
const revokeMutate = vi.fn();
const resendMutate = vi.fn((_body: unknown, opts?: MutateOptions) => opts?.onSuccess?.());

const PENDING = {
  id: "inv-1",
  hunt_id: "h1",
  email: "partner@example.com",
  role_granted: "member" as const,
  expires_at: "2026-08-20T00:00:00.000Z",
  link: "http://api.example/invite/tok-1",
  delivery_status: "queued" as const,
};

let invites: Invite[] = [PENDING];

vi.mock("../src/features/invites/api", () => ({
  invitationLinkForCurrentOrigin: (link: string) =>
    link.replace("http://api.example", "http://localhost"),
  useInvites: () => ({ data: invites }),
  useCreateInvite: () => ({ mutate: createMutate, isPending: false }),
  useRevokeInvite: () => ({ mutate: revokeMutate, isPending: false }),
  useResendInvite: () => ({ mutate: resendMutate, isPending: false }),
}));

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
    resendMutate.mockReset();
    resendMutate.mockImplementation((_body: unknown, opts?: MutateOptions) =>
      opts?.onSuccess?.(),
    );
    invites = [PENDING];
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

  it("surfaces a failed delivery and lets the Owner queue it again", async () => {
    invites = [{ ...PENDING, delivery_status: "failed" as const }];
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", {
        name: "Resend invitation email to partner@example.com",
      }),
    );

    expect(resendMutate).toHaveBeenCalledWith("inv-1", expect.any(Object));
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Invitation queued again", color: "green" }),
    );
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
