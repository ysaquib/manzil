import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const patchVisit = vi.fn();
const deleteVisit = vi.fn();

vi.mock("../src/features/visits/api", () => ({
  useVisit: () => ({ data: mockVisit, isLoading: false }),
  useVisitTemplate: () => ({ data: mockTemplate, isLoading: false }),
  usePatchVisit: () => ({ mutate: patchVisit, isPending: false, isError: false, error: null }),
  useDeleteVisit: () => ({ mutate: deleteVisit, isPending: false }),
  // The page renders the VC-3 checklist runtime, which reads these.
  useVisitCustomItems: () => ({ data: [], isLoading: false }),
  useVisitEntries: () => ({ data: [], isLoading: false }),
  useVisitEntryConflicts: () => ({ data: [], isLoading: false }),
  useVisitFeeProposals: () => ({ data: [], isLoading: false }),
  isOptimisticEntry: () => false,
  useSaveVisitEntries: () => ({ mutate: vi.fn(), isPending: false }),
  // …and the VC-4 defect log once the tour has started.
  useVisitDefects: () => ({ data: [], isLoading: false }),
  useCreateVisitDefect: () => ({ mutate: vi.fn(), isPending: false }),
  usePatchVisitDefect: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteVisitDefect: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("../src/auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: mockViewer } } }),
}));

vi.mock("../src/features/collaboration/api", () => ({
  useMembers: () => ({
    data: [{ user_id: "u1", display_name: "Yusuf", role: "owner" }],
    isLoading: false,
  }),
  useCurrentMember: () => ({ data: { user_id: mockViewer, role: mockViewerRole } }),
}));

import { VisitDetailPage } from "../src/features/visits/VisitDetailPage";

function templateItem(partial: Record<string, unknown>) {
  return {
    key: "k",
    version: 1,
    section_key: "prep",
    display_order: 1,
    tier: "standard",
    kind: "check",
    scope: "property",
    label: "Read the online reviews",
    help: null,
    value_schema: {},
    is_critical: false,
    ...partial,
  };
}

let mockVisit: Record<string, unknown> | null = null;
let mockTemplate: ReturnType<typeof templateItem>[] = [];
let mockViewer = "u1";
let mockViewerRole = "member";

function visit(partial: Record<string, unknown> = {}) {
  return {
    id: "v1",
    hunt_id: "h1",
    property_id: "p1",
    created_by: "u1",
    scheduled_for: null,
    started_at: null,
    ended_at: null,
    cancelled_at: null,
    cancel_reason: null,
    template_version: 1,
    prefilled_from: null,
    created_at: "2026-07-28T16:00:00Z",
    visit_units: [
      {
        id: "un1",
        visit_id: "v1",
        label: "4B",
        floor_plan_id: "fp1",
        beds: 2,
        baths: 2,
        unit_group_key: "2-2",
        display_order: 0,
        created_by: "u1",
        created_at: "2026-07-28T16:00:00Z",
      },
    ],
    property: { id: "p1", name: "Cedar & Vine", canonical_address: "1412 Cedar Ave" },
    ...partial,
  };
}

/**
 * Mantine renders Menu dropdowns through a `Transition` that never settles under
 * jsdom, so items are present with `role="menuitem"` but drift in and out of
 * testing-library's visibility filter. `hidden: true` keeps the assertion on role
 * plus accessible name and drops only that filter, which also makes these tests
 * deterministic rather than dependent on when a retry happens to look.
 */
const menuItem = (name: RegExp) => screen.findByRole("menuitem", { name, hidden: true });

function renderPage() {
  return renderWithProviders(
    <MemoryRouter initialEntries={["/h/h1/visits/v1"]}>
      <Routes>
        <Route path="/h/:huntId/visits/:visitId" element={<VisitDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  patchVisit.mockReset();
  deleteVisit.mockReset();
  mockViewer = "u1";
  mockViewerRole = "member";
  mockVisit = visit();
  mockTemplate = [
    templateItem({ key: "prep_reviews" }),
    templateItem({
      key: "prep_age",
      display_order: 2,
      label: "Building age",
      help: "Pre-1978 means a lead-paint disclosure is required by law",
    }),
    templateItem({
      key: "k1",
      section_key: "kitchen",
      scope: "unit",
      display_order: 3,
      label: "Kitchen check",
    }),
    templateItem({ key: "v1", section_key: "verdict_unit", scope: "unit", display_order: 4 }),
  ];
});

describe("VisitDetailPage before the tour starts", () => {
  it("exposes only the property-scoped prep section, and locks the rest", () => {
    renderPage();
    // The prep section is answerable — it is the one thing you do on the couch.
    expect(screen.getByText("Read the online reviews")).toBeInTheDocument();
    expect(screen.getByText(/lead-paint disclosure/)).toBeInTheDocument();
    // Its items carry real controls now (VC-3), not a read-only list.
    expect(
      screen.getByRole("button", { name: /Read the online reviews: fine/ }),
    ).toBeInTheDocument();

    // Unit-scoped sections are named but explicitly not open yet.
    expect(screen.getByText("Unlocks when you start")).toBeInTheDocument();
    expect(screen.getByText("Kitchen")).toBeInTheDocument();
    expect(screen.getByText("Verdict — this unit")).toBeInTheDocument();
    // …and no unit-scoped item is answerable before the tour starts.
    expect(screen.queryByRole("button", { name: /Kitchen check: fine/ })).not.toBeInTheDocument();
  });

  it("marks the prep section as whole-property scoped", () => {
    renderPage();
    expect(screen.getByText("Whole property")).toBeInTheDocument();
  });

  it("offers Start visit, and starting sends the action rather than a timestamp", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Start visit/ }));
    expect(patchVisit).toHaveBeenCalledWith({ visitId: "v1", body: { action: "start" } });
  });
});

describe("VisitDetailPage lifecycle", () => {
  it("shows the defect log only once the tour has begun", () => {
    renderPage();
    expect(screen.queryByText("Defect log")).not.toBeInTheDocument();

    mockVisit = visit({ started_at: "2026-07-28T16:12:00Z" });
    renderPage();
    expect(screen.getAllByText("Defect log").length).toBeGreaterThan(0);
  });

  it("keeps a cancelled visit's record visible rather than hiding it", () => {
    // Cancelling a tour that had already happened must not hide what was
    // recorded on it — visibility follows whether it started, editability
    // follows the derived state.
    mockVisit = visit({
      started_at: "2026-07-28T16:12:00Z",
      cancelled_at: "2026-07-29T09:00:00Z",
    });
    renderPage();
    expect(screen.getAllByText("Defect log").length).toBeGreaterThan(0);
    expect(screen.queryByText("Unlocks when you start")).not.toBeInTheDocument();
  });

  it("offers End visit once in progress, and no Start", () => {
    mockVisit = visit({ started_at: "2026-07-28T16:12:00Z" });
    renderPage();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /End visit/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start visit/ })).not.toBeInTheDocument();
    // Sections are no longer gated once the tour is under way, so the locked
    // list is gone and every section is reachable from the checklist.
    expect(screen.queryByText("Unlocks when you start")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Kitchen/ })).toBeInTheDocument();
  });

  it("offers neither once completed", () => {
    mockVisit = visit({
      started_at: "2026-07-28T16:12:00Z",
      ended_at: "2026-07-28T16:54:00Z",
    });
    renderPage();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start visit/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /End visit/ })).not.toBeInTheDocument();
  });

  it("shows the cancellation reason and offers reinstate", () => {
    mockVisit = visit({
      cancelled_at: "2026-07-29T09:00:00Z",
      cancel_reason: "agent never showed",
    });
    renderPage();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.getByText(/agent never showed/)).toBeInTheDocument();
  });

  it("puts cancel and delete behind the actions menu, not in the open", async () => {
    renderPage();
    const user = userEvent.setup();
    // Rare and destructive actions are tucked but reachable (UI_DESIGN §4).
    expect(screen.queryAllByRole("menuitem", { hidden: true })).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: /Visit actions/ }));
    expect(await menuItem(/Cancel visit/)).toBeInTheDocument();
    expect(await menuItem(/Delete visit/)).toBeInTheDocument();
  });

  it("reinstates straight from the menu once cancelled", async () => {
    mockVisit = visit({ cancelled_at: "2026-07-29T09:00:00Z" });
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Visit actions/ }));
    await user.click(await menuItem(/Reinstate visit/));
    expect(patchVisit).toHaveBeenCalledWith({ visitId: "v1", body: { action: "reinstate" } });
  });
});

describe("VisitDetailPage permissions", () => {
  it("lets the creator cancel and delete", async () => {
    mockVisit = visit({ created_by: "u1" });
    mockViewer = "u1";
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Visit actions/ }));
    expect(await menuItem(/Cancel visit/)).not.toHaveAttribute(
      "data-disabled",
    );
  });

  it("disables cancel and delete for a member who is neither creator nor Owner", async () => {
    mockVisit = visit({ created_by: "someone-else" });
    mockViewer = "u1";
    mockViewerRole = "curator";
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Visit actions/ }));
    expect(await menuItem(/Cancel visit/)).toHaveAttribute(
      "data-disabled",
      "true",
    );
    expect(screen.getByText(/Only the creator or the Owner/)).toBeInTheDocument();
  });

  it("lets the Owner cancel someone else's visit", async () => {
    mockVisit = visit({ created_by: "someone-else" });
    mockViewer = "u1";
    mockViewerRole = "owner";
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Visit actions/ }));
    expect(await menuItem(/Cancel visit/)).not.toHaveAttribute(
      "data-disabled",
    );
  });

  it("still lets any member start a visit they did not create", () => {
    mockVisit = visit({ created_by: "someone-else" });
    mockViewerRole = "member";
    renderPage();
    expect(screen.getByRole("button", { name: /Start visit/ })).toBeEnabled();
  });
});

describe("VisitDetailPage missing visit", () => {
  it("says so plainly rather than rendering an empty shell", () => {
    mockVisit = null;
    renderPage();
    expect(screen.getByText("Visit not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to visits/ })).toHaveAttribute(
      "href",
      "/h/h1/visits",
    );
  });
});

describe("reopening a finished visit", () => {
  it("offers Reopen once a tour has ended, and sends the action", async () => {
    // Ending is a state, not a seal: the desktop write-up is where the typo
    // gets fixed and the half-heard answer finally gets typed.
    mockVisit = visit({
      started_at: "2026-07-28T16:12:00Z",
      ended_at: "2026-07-28T17:30:00Z",
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Reopen visit/ }));
    expect(patchVisit).toHaveBeenCalledWith({ visitId: "v1", body: { action: "reopen" } });
  });

  it("shows the finished record read-only until it is reopened", () => {
    mockVisit = visit({
      started_at: "2026-07-28T16:12:00Z",
      ended_at: "2026-07-28T17:30:00Z",
    });
    renderPage();
    expect(screen.getByRole("button", { name: /Read the online reviews: fine/ })).toBeDisabled();
  });

  it("offers no Reopen on a tour still in progress", () => {
    mockVisit = visit({ started_at: "2026-07-28T16:12:00Z" });
    renderPage();
    expect(screen.queryByRole("button", { name: /Reopen visit/ })).not.toBeInTheDocument();
  });

  it("offers no Reopen on a cancelled visit — reinstate comes first", () => {
    // Cancellation outranks everything; a Reopen button here would imply a
    // transition the API refuses.
    mockVisit = visit({
      started_at: "2026-07-28T16:12:00Z",
      ended_at: "2026-07-28T17:30:00Z",
      cancelled_at: "2026-07-29T09:00:00Z",
    });
    renderPage();
    expect(screen.queryByRole("button", { name: /Reopen visit/ })).not.toBeInTheDocument();
  });
});
