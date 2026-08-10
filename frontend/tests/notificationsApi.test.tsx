import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();
vi.mock("../src/lib/apiClient", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));
vi.mock("../src/features/admin/useGhostMode", () => ({
  useGhostMutationPath: () => (path: string) => path,
}));

import {
  NOTIFICATION_EVENTS,
  useSaveAccountNotificationPreferences,
} from "../src/features/notifications/api";

let queryClient: QueryClient;
let invalidated: unknown[][];

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  apiFetch.mockReset();
  invalidated = [];
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const original = queryClient.invalidateQueries.bind(queryClient);
  queryClient.invalidateQueries = ((filters?: { queryKey?: unknown[] }) => {
    if (filters?.queryKey) invalidated.push(filters.queryKey);
    return original(filters as never);
  }) as typeof queryClient.invalidateQueries;
});

describe("account notification preferences", () => {
  it("invalidates inherited Hunt preferences after changing an account default", async () => {
    const email = Object.fromEntries(
      NOTIFICATION_EVENTS.map((event) => [event, event === "checkpoint_waiting"]),
    ) as Record<(typeof NOTIFICATION_EVENTS)[number], boolean>;
    apiFetch.mockResolvedValue({ email });
    const { result } = renderHook(() => useSaveAccountNotificationPreferences(), { wrapper });

    result.current.mutate({ email });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(queryClient.getQueryData(["notification_preferences", "account"])).toEqual({ email });
    expect(invalidated).toContainEqual(["notification_preferences", "hunt"]);
  });
});
