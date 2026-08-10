import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SignOutPage } from "../src/auth/SignOutPage";

const { navigate, signOut } = vi.hoisted(() => ({ navigate: vi.fn(), signOut: vi.fn() }));
vi.mock("../src/lib/supabase", () => ({
  supabase: { auth: { signOut } },
}));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

function renderSignOut(entry = "/signout") {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["profile", "user"], { default_display_name: "Yusuf" });
  render(
    <MantineProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[entry]}>
          <SignOutPage />
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
  return queryClient;
}

describe("SignOutPage", () => {
  beforeEach(() => {
    navigate.mockReset();
    signOut.mockResolvedValue({ error: null });
  });

  it("clears the local session and cached user data before returning to login", async () => {
    const queryClient = renderSignOut();

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login", { replace: true }));
    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
    await waitFor(() => expect(queryClient.getQueryData(["profile", "user"])).toBeUndefined());
  });

  // Signing out from an invitation means "wrong account", not "I am leaving" —
  // the next account has to land back on the invitation.
  it("carries an invitation target through to the login page", async () => {
    renderSignOut("/signout?next=%2Finvite%2Ftok-1");

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/login?next=%2Finvite%2Ftok-1", { replace: true }),
    );
  });

  it("refuses a return target that is not an invitation", async () => {
    renderSignOut("/signout?next=https%3A%2F%2Fevil.example");

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login", { replace: true }));
  });
});
