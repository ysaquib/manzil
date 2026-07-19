import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HuntMember } from "./api";

const useAuth = vi.fn();

vi.mock("../../auth/useAuth", () => ({
  useAuth: () => useAuth(),
}));

vi.mock("../../lib/supabase", () => ({
  supabase: {
    from: () => ({
      select: () => ({
        eq: () => Promise.resolve({ data: [], error: null }),
        in: () => Promise.resolve({ data: [], error: null }),
      }),
    }),
  },
}));

import { useCurrentMember } from "./api";

const member: HuntMember = {
  hunt_id: "h1",
  user_id: "u1",
  role: "member",
  color: "moss",
  display_name: "Yusuf",
};

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useCurrentMember", () => {
  beforeEach(() => {
    useAuth.mockReset();
  });

  it("returns the matching HuntMember for the signed-in user", async () => {
    useAuth.mockReturnValue({ session: { user: { id: "u1" } } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(["hunt_members", "h1"], [member, { ...member, user_id: "u2", color: "moss" }]);

    const { result } = renderHook(() => useCurrentMember("h1"), { wrapper: wrapper(client) });

    await waitFor(() => expect(result.current.data).toEqual(member));
  });

  it("returns undefined when there is no session", async () => {
    useAuth.mockReturnValue({ session: null });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(["hunt_members", "h1"], [member]);

    const { result } = renderHook(() => useCurrentMember("h1"), { wrapper: wrapper(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it("returns undefined when the user is not in the members list", async () => {
    useAuth.mockReturnValue({ session: { user: { id: "u-missing" } } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(["hunt_members", "h1"], [member]);

    const { result } = renderHook(() => useCurrentMember("h1"), { wrapper: wrapper(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});
