import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useHunt = vi.fn();
const useRubric = vi.fn();
const useAuth = vi.fn();

vi.mock("../../auth/useAuth", () => ({
  useAuth: () => useAuth(),
}));

vi.mock("../hunts/api", () => ({
  useHunt: (huntId: string) => useHunt(huntId),
}));

vi.mock("./api", () => ({
  useRubric: (huntId: string) => useRubric(huntId),
}));

import { CreateRubricPrompt } from "./CreateRubricPrompt";

function renderPrompt(path = "/h/h1", huntId = "h1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/h/:huntId/*" element={<CreateRubricPrompt huntId={huntId} />} />
            <Route path="/h/:huntId/rubric" element={<div>Rubric page</div>} />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe("CreateRubricPrompt", () => {
  beforeEach(() => {
    useAuth.mockReturnValue({
      session: { user: { id: "owner-1" } },
      loading: false,
    });
    useHunt.mockReturnValue({
      data: { id: "h1", owner_id: "owner-1", name: "Hunt" },
      isLoading: false,
    });
    useRubric.mockReturnValue({ data: [], isLoading: false });
  });

  it("shows for an owner when no criteria are enabled", async () => {
    renderPrompt();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/no criteria selected yet/i)).toBeInTheDocument();
  });

  it("shows when all saved criteria are disabled", async () => {
    useRubric.mockReturnValue({
      data: [{ enabled: false }, { enabled: false }],
      isLoading: false,
    });
    renderPrompt();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("does not show for non-owners", () => {
    useHunt.mockReturnValue({
      data: { id: "h1", owner_id: "someone-else", name: "Hunt" },
      isLoading: false,
    });
    renderPrompt();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not show when at least one criterion is enabled", () => {
    useRubric.mockReturnValue({
      data: [{ enabled: false }, { enabled: true }],
      isLoading: false,
    });
    renderPrompt();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("is suppressed on the rubric route", () => {
    renderPrompt("/h/h1/rubric");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Cancel dismisses for the current visit", async () => {
    renderPrompt();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("Create Rubric navigates to the rubric page", async () => {
    renderPrompt();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create Rubric" }));
    expect(await screen.findByText("Rubric page")).toBeInTheDocument();
  });

  it("resets dismissal when the hunt id changes", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <MantineProvider>
          <MemoryRouter initialEntries={["/h/h1"]}>
            <Routes>
              <Route path="/h/:huntId/*" element={<CreateRubricPrompt huntId="h1" />} />
            </Routes>
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    useHunt.mockReturnValue({
      data: { id: "h2", owner_id: "owner-1", name: "Other" },
      isLoading: false,
    });
    useRubric.mockReturnValue({ data: [], isLoading: false });

    rerender(
      <QueryClientProvider client={client}>
        <MantineProvider>
          <MemoryRouter initialEntries={["/h/h2"]}>
            <Routes>
              <Route path="/h/:huntId/*" element={<CreateRubricPrompt huntId="h2" />} />
            </Routes>
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
