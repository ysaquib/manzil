import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  useCatalog: () => ({
    data: [{ key: "beds", label: "Beds", category: "unit", domain: "rent", value_schema: { type: "number" }, default_options: [], extraction_hint: "", requires_tool: null, refresh_class: "static" }],
    isLoading: false,
    error: null,
  }),
  useRubric: () => ({ data: mockSaved, isLoading: false, error: null }),
}));

vi.mock("./RubricEditor", () => ({
  RubricEditor: () => <div>Rubric editor</div>,
}));

vi.mock("./RubricView", () => ({
  RubricView: () => <div>Rubric view</div>,
}));

import { RubricPage } from "./RubricPage";

let mockSaved: { enabled: boolean }[] = [];

function renderPage() {
  return render(
    <MantineProvider>
      <MemoryRouter initialEntries={["/h/h1/rubric"]}>
        <Routes>
          <Route path="/h/:huntId/rubric" element={<RubricPage />} />
        </Routes>
      </MemoryRouter>
    </MantineProvider>,
  );
}

describe("RubricPage", () => {
  it("opens the editor when no criteria are enabled", () => {
    mockSaved = [{ enabled: false }, { enabled: false }];
    renderPage();
    expect(screen.getByText("Rubric editor")).toBeInTheDocument();
    expect(screen.queryByText("Rubric view")).not.toBeInTheDocument();
  });

  it("keeps view mode when at least one criterion is enabled", () => {
    mockSaved = [{ enabled: false }, { enabled: true }];
    renderPage();
    expect(screen.getByText("Rubric view")).toBeInTheDocument();
    expect(screen.queryByText("Rubric editor")).not.toBeInTheDocument();
  });
});
