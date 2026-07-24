import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MantineProvider } from "@mantine/core";
import { render, waitFor } from "@testing-library/react";
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

describe("SignOutPage", () => {
  beforeEach(() => signOut.mockResolvedValue({ error: null }));

  it("clears the local session and cached user data before returning to login", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["profile", "user"], { default_display_name: "Yusuf" });
    render(
      <MantineProvider>
        <QueryClientProvider client={queryClient}>
          <SignOutPage />
        </QueryClientProvider>
      </MantineProvider>,
    );

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login", { replace: true }));
    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
    await waitFor(() => expect(queryClient.getQueryData(["profile", "user"])).toBeUndefined());
  });
});
