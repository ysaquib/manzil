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

let demo = false;
vi.mock("../src/lib/demo", () => ({
  isDemo: () => demo,
}));

let replayState = { running: false, finished: false };
const replayListeners = new Set<() => void>();
vi.mock("../src/features/demo/replay/replayEngine", () => ({
  subscribeToReplay: (listener: () => void) => {
    replayListeners.add(listener);
    return () => replayListeners.delete(listener);
  },
  replaySnapshot: () => replayState,
}));

import {
  NOTIFICATION_EVENTS,
  useAttention,
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
  demo = false;
  replayState = { running: false, finished: false };
  replayListeners.clear();
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

describe("useAttention", () => {
  it("fetches the server's severity summary outside demo mode", async () => {
    demo = false;
    apiFetch.mockResolvedValue({
      waiting_checkpoint_count: 1,
      failed: 1,
      waiting_user: 0,
      running: 0,
      task_status: "failed",
    });
    const { result } = renderHook(() => useAttention("hunt-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiFetch).toHaveBeenCalledWith("/v1/hunts/hunt-1/attention");
    expect(result.current.data?.task_status).toBe("failed");
  });

  it("reports a playing Replay Capture as running, without touching the network", async () => {
    // A demo session never enqueues a real Job, so the server always reports
    // nothing running for it -- but a playing recording is real activity from
    // the visitor's point of view, and the Tasks navbar dot should say so.
    demo = true;
    replayState = { running: true, finished: false };
    const { result } = renderHook(() => useAttention("hunt-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      waiting_checkpoint_count: 0,
      failed: 0,
      waiting_user: 0,
      running: 1,
      task_status: "running",
    });
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("reports nothing running once a demo replay finishes", async () => {
    demo = true;
    replayState = { running: false, finished: true };
    const { result } = renderHook(() => useAttention("hunt-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.task_status).toBeNull();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
