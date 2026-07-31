// The pending-write indicator (VC-6).
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/apiClient", () => ({
  apiFetch: vi.fn().mockResolvedValue([]),
  ApiError: class ApiError extends Error {},
}));

import { SyncBadge, pendingLabel } from "../src/features/visits/SyncBadge";
import { installMutationDefaults, SAVE_ENTRIES_KEY } from "../src/lib/offline";

afterEach(() => {
  onlineManager.setOnline(true);
});

function renderBadge(client: QueryClient) {
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <SyncBadge />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("pendingLabel", () => {
  it("counts in plain words, singular and plural", () => {
    expect(pendingLabel(1)).toBe("1 change waiting to sync");
    expect(pendingLabel(4)).toBe("4 changes waiting to sync");
  });
});

describe("SyncBadge", () => {
  it("says nothing when nothing is pending — the usual state", () => {
    const client = new QueryClient();
    renderBadge(client);
    expect(screen.queryByText(/waiting to sync/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Saving/)).not.toBeInTheDocument();
  });

  it("counts writes queued while the signal is gone", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    installMutationDefaults(client);
    renderBadge(client);

    // Offline is what pauses a mutation; this is the tour-in-a-basement case.
    onlineManager.setOnline(false);
    client
      .getMutationCache()
      .build(client, { mutationKey: SAVE_ENTRIES_KEY })
      .execute({ visitId: "v1", entries: [{ item_key: "a", is_custom: false }] })
      .catch(() => undefined);
    client
      .getMutationCache()
      .build(client, { mutationKey: SAVE_ENTRIES_KEY })
      .execute({ visitId: "v1", entries: [{ item_key: "b", is_custom: false }] })
      .catch(() => undefined);

    await waitFor(() =>
      expect(screen.getByText("2 changes waiting to sync")).toBeInTheDocument(),
    );
  });

  it("clears once the queue flushes on reconnect", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    installMutationDefaults(client);
    renderBadge(client);

    onlineManager.setOnline(false);
    client
      .getMutationCache()
      .build(client, { mutationKey: SAVE_ENTRIES_KEY })
      .execute({ visitId: "v1", entries: [{ item_key: "a", is_custom: false }] })
      .catch(() => undefined);
    await waitFor(() => expect(screen.getByText(/waiting to sync/)).toBeInTheDocument());

    onlineManager.setOnline(true);
    await client.resumePausedMutations();
    await waitFor(() => expect(screen.queryByText(/waiting to sync/)).not.toBeInTheDocument());
  });
});
