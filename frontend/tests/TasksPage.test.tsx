import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../src/features/jobs/TasksActivePage", () => ({
  TasksActivePage: () => <div>Active tasks</div>,
}));
vi.mock("../src/features/jobs/TasksHistoryTab", () => ({
  TasksHistoryTab: () => <div>Run history</div>,
}));
vi.mock("../src/features/jobs/StatusLegend", () => ({ StatusLegend: () => null }));

import { TasksPage } from "../src/features/jobs/TasksPage";

function renderAt(url: string) {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/h/:huntId/tasks" element={<TasksPage />} />
        </Routes>
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe("TasksPage", () => {
  it("opens Active by default", () => {
    renderAt("/h/h1/tasks");
    expect(screen.getByRole("tab", { name: "Active" })).toHaveAttribute("aria-selected", "true");
  });

  // The Overview links a failed row straight to the run that failed.
  it("opens History when the URL asks for it", () => {
    renderAt("/h/h1/tasks?tab=history");
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to Active for an unknown tab", () => {
    renderAt("/h/h1/tasks?tab=nonsense");
    expect(screen.getByRole("tab", { name: "Active" })).toHaveAttribute("aria-selected", "true");
  });
});
