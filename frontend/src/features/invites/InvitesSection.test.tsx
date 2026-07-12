import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const createMutate = vi.fn((_body: unknown, opts?: { onSuccess?: () => void }) =>
  opts?.onSuccess?.(),
);

vi.mock("./api", () => ({
  useInvites: () => ({ data: [] }),
  useCreateInvite: () => ({ mutate: createMutate, isPending: false }),
  useRevokeInvite: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { InvitesSection } from "./InvitesSection";

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
});
