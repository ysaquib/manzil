import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const createVisit = vi.fn();
const navigate = vi.fn();

vi.mock("../src/features/listings/api", () => ({
  useListings: () => ({ data: mockListings, isLoading: false }),
}));

vi.mock("../src/features/visits/api", () => ({
  useCreateVisit: () => ({
    mutateAsync: createVisit,
    isPending: false,
    isError: false,
    error: null,
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

import { VisitCreatePage } from "../src/features/visits/VisitCreatePage";

function plan(id: string, name: string, beds: number, baths: number) {
  return {
    id,
    property_id: "p1",
    source_id: "s1",
    plan_name: name,
    beds,
    baths,
    sqft_min: 1040,
    sqft_max: 1040,
    rent_min: 2340,
    rent_max: 2400,
    deposit: null,
    availability_date: null,
    available_units: 3,
    is_current: true,
  };
}

let mockListings: unknown[] = [];

function renderPage() {
  return renderWithProviders(
    <MemoryRouter initialEntries={["/h/h1/visits/new"]}>
      <Routes>
        <Route path="/h/:huntId/visits/new" element={<VisitCreatePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  createVisit.mockReset();
  createVisit.mockResolvedValue({ id: "new-visit" });
  navigate.mockReset();
  mockListings = [
    {
      id: "l1",
      property_id: "p1",
      property: {
        id: "p1",
        name: "Cedar & Vine",
        canonical_address: "1412 Cedar Ave",
        floor_plans: [
          plan("fp1", "The Alder", 2, 2),
          plan("fp2", "The Birch", 2, 2),
          plan("fp3", "The Cedar", 1, 1),
        ],
        sources: [],
      },
      scores: [],
    },
    {
      id: "l2",
      property_id: "p2",
      property: {
        id: "p2",
        name: "Marlowe Court",
        canonical_address: "9 Marlowe Rd",
        floor_plans: [],
        sources: [],
      },
      scores: [],
    },
  ];
});

/**
 * Mantine renders a Combobox dropdown through a `Transition`, which never
 * resolves under jsdom — the options are in the DOM with `role="option"` but
 * fail testing-library's visibility filter. `hidden: true` keeps the assertion
 * on role plus accessible name and drops only that filter; it is a jsdom
 * artifact, not a statement about the real dropdown.
 */
const option = (name: string | RegExp) => screen.findByRole("option", { name, hidden: true });
const options = () => screen.queryAllByRole("option", { hidden: true });

async function pickProperty(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole("combobox", { name: /Property/ }));
  await user.click(await option(name));
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

describe("VisitCreatePage", () => {
  it("offers only properties already in this hunt", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: /Property/ }));
    expect(await option("Cedar & Vine")).toBeInTheDocument();
    expect(await option("Marlowe Court")).toBeInTheDocument();
    expect(options()).toHaveLength(2);
  });

  it("groups a property's plans by derived Unit Group", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");

    expect(screen.getByText("2 bd / 2 ba")).toBeInTheDocument();
    expect(screen.getByText("1 bd / 1 ba")).toBeInTheDocument();
    expect(screen.getByText("2 plans")).toBeInTheDocument();
    expect(screen.getByText("The Alder")).toBeInTheDocument();
  });

  it("seeds a unit to name on site when a plan is ticked, and unseeds when unticked", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");

    await user.click(screen.getByRole("checkbox", { name: /The Alder/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("1 unit")).toBeInTheDocument();
    // Unnamed on purpose — the number is never known in advance.
    expect(screen.getByPlaceholderText("Name it on site")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(screen.getByRole("checkbox", { name: /The Alder/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/No units yet/)).toBeInTheDocument();
  });

  it("adds a described unit that maps to no advertised plan", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await user.click(screen.getByRole("button", { name: /Add another unit/ }));
    await user.type(screen.getByRole("textbox", { name: /What will you call it/ }), "basement 2br");
    await user.click(screen.getByRole("combobox", { name: /What is it/ }));
    await user.click(await option(/describe it/));
    await user.click(screen.getByRole("button", { name: "Add unit" }));

    expect(screen.getByDisplayValue("basement 2br")).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();
    expect(screen.getByText("not advertised")).toBeInTheDocument();
  });

  it("refuses a duplicate unit label case-insensitively", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");
    await user.click(screen.getByRole("checkbox", { name: /The Alder/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await user.type(screen.getByPlaceholderText("Name it on site"), "4B");
    await user.click(screen.getByRole("button", { name: /Add another unit/ }));
    await user.type(screen.getByRole("textbox", { name: /What will you call it/ }), "4b");

    expect(screen.getByText(/already has a unit with that name/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add unit" })).toBeDisabled();
  });

  it("submits the collected units and lands on the new visit", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");
    await user.click(screen.getByRole("checkbox", { name: /The Alder/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByPlaceholderText("Name it on site"), "4B");
    await user.click(screen.getByRole("button", { name: /Create visit/ }));

    await waitFor(() => expect(createVisit).toHaveBeenCalledTimes(1));
    expect(createVisit).toHaveBeenCalledWith({
      property_id: "p1",
      units: [
        {
          label: "4B",
          floor_plan_id: "fp1",
          // A plan-backed unit sends no shape: the server takes beds/baths from
          // the Floor Plan so the Unit Group key matches the listing's grouping.
          beds: null,
          baths: null,
          display_order: 0,
        },
      ],
    });
    expect(navigate).toHaveBeenCalledWith("/h/h1/visits/new-visit");
  });

  it("still creates a visit with no units — you can add them on site", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: /Create visit/ }));

    await waitFor(() => expect(createVisit).toHaveBeenCalledTimes(1));
    expect(createVisit).toHaveBeenCalledWith({ property_id: "p1", units: [] });
  });

  it("says so plainly when a listing has no current plans, instead of an empty step", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Marlowe Court");
    expect(screen.getByText(/no current floor plans yet/)).toBeInTheDocument();
  });

  it("gives an unnamed unit a placeholder label the API will accept", async () => {
    renderPage();
    const user = userEvent.setup();
    await pickProperty(user, "Cedar & Vine");
    await user.click(screen.getByRole("checkbox", { name: /The Birch/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: /Create visit/ }));

    await waitFor(() => expect(createVisit).toHaveBeenCalledTimes(1));
    expect(createVisit.mock.calls[0][0].units[0].label).toBe("Unit 1");
  });
});
