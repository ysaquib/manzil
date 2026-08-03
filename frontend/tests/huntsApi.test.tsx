import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useAuth = vi.hoisted(() => vi.fn());
const from = vi.hoisted(() => vi.fn());

vi.mock("../src/auth/useAuth", () => ({ useAuth }));
vi.mock("../src/lib/supabase", () => ({ supabase: { from } }));

import { useHunts } from "../src/features/hunts/api";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useHunts", () => {
  beforeEach(() => {
    useAuth.mockReturnValue({ session: { user: { id: "admin-1" } } });
    from.mockReset();
  });

  it("explicitly limits the switcher to the signed-in user's Hunt memberships", async () => {
    const order = vi.fn().mockResolvedValue({ data: [], error: null });
    const is = vi.fn(() => ({ order }));
    const eq = vi.fn(() => ({ is }));
    const select = vi.fn(() => ({ eq }));
    from.mockReturnValue({ select });

    const { result } = renderHook(() => useHunts(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(from).toHaveBeenCalledWith("hunts");
    expect(select).toHaveBeenCalledWith("*, hunt_members!inner(user_id)");
    expect(eq).toHaveBeenCalledWith("hunt_members.user_id", "admin-1");
  });
});
