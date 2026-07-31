import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

vi.mock("../src/features/visits/api", () => ({
  useVisits: () => ({ data: mockVisits, isLoading: false, isError: false, error: null }),
}));

vi.mock("../src/features/collaboration/api", () => ({
  useMembers: () => ({
    data: [
      { user_id: "u1", display_name: "Yusuf", role: "owner" },
      { user_id: "u2", display_name: "Sana", role: "member" },
    ],
    isLoading: false,
  }),
}));

import { VisitsPage } from "../src/features/visits/VisitsPage";

interface MockVisit {
  id: string;
  hunt_id: string;
  property_id: string;
  created_by: string;
  scheduled_for: string | null;
  started_at: string | null;
  ended_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  template_version: number;
  prefilled_from: null;
  created_at: string;
  visit_units: {
    id: string;
    visit_id: string;
    label: string;
    floor_plan_id: string | null;
    beds: number;
    baths: number;
    unit_group_key: string;
    display_order: number;
    created_by: string;
    created_at: string;
  }[];
  property: { id: string; name: string; canonical_address: string };
}

function unit(label: string, custom = false) {
  return {
    id: `unit-${label}`,
    visit_id: "v",
    label,
    floor_plan_id: custom ? null : "fp1",
    beds: 2,
    baths: 2,
    unit_group_key: "2-2",
    display_order: 0,
    created_by: "u1",
    created_at: "2026-07-28T16:00:00Z",
  };
}

function visit(partial: Partial<MockVisit> & { id: string; name: string }): MockVisit {
  const { name, ...rest } = partial;
  return {
    hunt_id: "h1",
    property_id: `p-${partial.id}`,
    created_by: "u1",
    scheduled_for: null,
    started_at: null,
    ended_at: null,
    cancelled_at: null,
    cancel_reason: null,
    template_version: 1,
    prefilled_from: null,
    created_at: "2026-07-28T16:00:00Z",
    visit_units: [unit("4B")],
    property: { id: `p-${partial.id}`, name, canonical_address: "1 Test St" },
    ...rest,
  } as MockVisit;
}

let mockVisits: MockVisit[] = [];

function renderPage() {
  return renderWithProviders(
    <MemoryRouter initialEntries={["/h/h1/visits"]}>
      <Routes>
        <Route path="/h/:huntId/visits" element={<VisitsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("VisitsPage", () => {
  it("renders all four derived states from timestamps alone", () => {
    mockVisits = [
      visit({ id: "1", name: "Cedar & Vine", started_at: "2026-07-28T16:12:00Z" }),
      visit({ id: "2", name: "Marlowe Court", scheduled_for: "2026-07-31T10:30:00Z" }),
      visit({
        id: "3",
        name: "The Ashby",
        started_at: "2026-07-12T11:00:00Z",
        ended_at: "2026-07-12T11:40:00Z",
      }),
      visit({
        id: "4",
        name: "Brightwater Lofts",
        cancelled_at: "2026-07-04T14:00:00Z",
        cancel_reason: "agent never showed",
      }),
    ];
    renderPage();

    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Planned")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.getByText("Cedar & Vine")).toBeInTheDocument();
  });

  it("shows a cancellation reason, because the no-show is information", () => {
    mockVisits = [
      visit({
        id: "1",
        name: "Brightwater Lofts",
        cancelled_at: "2026-07-04T14:00:00Z",
        cancel_reason: "agent never showed",
      }),
    ];
    renderPage();
    expect(screen.getByText(/agent never showed/)).toBeInTheDocument();
  });

  it("filters by state and offers a way back when the filter empties the list", async () => {
    mockVisits = [
      visit({ id: "1", name: "Cedar & Vine", started_at: "2026-07-28T16:12:00Z" }),
      visit({ id: "2", name: "Marlowe Court" }),
    ];
    renderPage();
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: /Planned 1/ }));
    expect(screen.getByText("Marlowe Court")).toBeInTheDocument();
    expect(screen.queryByText("Cedar & Vine")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /Done 0/ }));
    expect(screen.getByText(/No visits in that state/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Show all 2/ }));
    expect(screen.getByText("Cedar & Vine")).toBeInTheDocument();
  });

  it("hides the cancelled filter when nothing is cancelled", () => {
    mockVisits = [visit({ id: "1", name: "Cedar & Vine" })];
    renderPage();
    expect(screen.queryByRole("radio", { name: /Cancelled/ })).not.toBeInTheDocument();
  });

  it("names who set a visit up, since attendance is not modelled yet", () => {
    mockVisits = [visit({ id: "1", name: "Cedar & Vine", created_by: "u2" })];
    renderPage();
    expect(screen.getByText(/set up by Sana/)).toBeInTheDocument();
  });

  it("marks a unit the listing never advertised", () => {
    mockVisits = [
      visit({ id: "1", name: "Cedar & Vine", visit_units: [unit("the corner one", true)] }),
    ];
    renderPage();
    expect(screen.getByText("the corner one")).toBeInTheDocument();
  });

  it("offers a purposeful empty state rather than a bare 'no data'", () => {
    mockVisits = [];
    renderPage();
    expect(screen.getByText("No visits yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Plan your first visit/ })).toHaveAttribute(
      "href",
      "/h/h1/visits/new",
    );
    // No filter to show when there is nothing to filter.
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("links each row and the header action into the flow", () => {
    mockVisits = [visit({ id: "abc", name: "Cedar & Vine" })];
    renderPage();
    expect(screen.getByRole("link", { name: "Cedar & Vine" })).toHaveAttribute(
      "href",
      "/h/h1/visits/abc",
    );
    expect(screen.getByRole("link", { name: /New visit/ })).toHaveAttribute(
      "href",
      "/h/h1/visits/new",
    );
  });

  it("does not crash when a visit has no units yet", () => {
    mockVisits = [visit({ id: "1", name: "Cedar & Vine", visit_units: [] })];
    renderPage();
    expect(screen.getByText("No units yet")).toBeInTheDocument();
  });
});
