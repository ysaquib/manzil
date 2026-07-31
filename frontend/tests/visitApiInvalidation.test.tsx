// Cache-invalidation contract for the visit mutations (VC-4, extended VC-6).
//
// Regression guard for a bug that only showed up in the running app: saving a
// checklist answer can create a row in *another* table — marking a Check as a
// problem promotes it into the defect log, and a late-flushing offline write can
// fork an answer — so the entry write has to invalidate those queries too. The
// unit tests all passed while the log silently lagged.
//
// Since VC-6 the mutation function and its invalidation live on the query client
// rather than in the hook, because a write restored from storage is rebuilt in a
// page where the hook's closure is gone. Installing them here is what makes this
// test exercise the contract that actually ships.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();
vi.mock("../src/lib/apiClient", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
  ApiError: class ApiError extends Error {},
}));
vi.mock("../src/lib/supabase", () => ({ supabase: {} }));

import { useSaveVisitEntries } from "../src/features/visits/api";
import { installMutationDefaults } from "../src/lib/offline";

let queryClient: QueryClient;
let invalidated: unknown[][];

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockResolvedValue([]);
  invalidated = [];
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  installMutationDefaults(queryClient);
  const original = queryClient.invalidateQueries.bind(queryClient);
  queryClient.invalidateQueries = ((filters?: { queryKey?: unknown[] }) => {
    if (filters?.queryKey) invalidated.push(filters.queryKey);
    return original(filters as never);
  }) as typeof queryClient.invalidateQueries;
});

describe("useSaveVisitEntries", () => {
  it("invalidates the defect log as well as the answers", async () => {
    const { result } = renderHook(() => useSaveVisitEntries("v1", "me"), { wrapper });
    result.current.mutate([{ item_key: "kitchen_disposal", is_custom: false, value: "problem" }]);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated).toContainEqual(["visit_entries", "v1"]);
    expect(invalidated).toContainEqual(["visit_defects", "v1"]);
    expect(invalidated).toContainEqual(["visit_entry_conflicts", "v1"]);
  });

  it("puts the batch to the one write path for answers", async () => {
    const { result } = renderHook(() => useSaveVisitEntries("v1", "me"), { wrapper });
    result.current.mutate([{ item_key: "prep_reviews", is_custom: false, value: "ok" }]);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiFetch).toHaveBeenCalledWith("/v1/visits/v1/entries", {
      method: "PUT",
      body: { entries: [{ item_key: "prep_reviews", is_custom: false, value: "ok" }] },
    });
  });
});
