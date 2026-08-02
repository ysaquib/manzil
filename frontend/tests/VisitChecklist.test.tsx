import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "./testUtils";

const saveEntries = vi.fn();

vi.mock("../src/features/visits/api", () => ({
  useVisitTemplate: () => ({ data: mockTemplate, isLoading: false }),
  useVisitCustomItems: () => ({ data: mockCustom, isLoading: false }),
  useVisitEntries: () => ({ data: mockEntries, isLoading: false }),
  useVisitEntryConflicts: () => ({ data: mockConflicts, isLoading: false }),
  useVisitFeeProposals: () => ({ data: [], isLoading: false }),
  useSaveVisitEntries: () => ({ mutate: saveEntries, isPending: false }),
  isOptimisticEntry: (entry: { id: string }) => entry.id.startsWith("optimistic:"),
}));

vi.mock("../src/features/collaboration/api", () => ({
  useMembers: () => ({
    data: [
      { user_id: "me", display_name: "Yusuf" },
      { user_id: "you", display_name: "Sana" },
    ],
    isLoading: false,
  }),
}));

vi.mock("../src/auth/useAuth", () => ({
  useAuth: () => ({ session: { user: { id: "me" } } }),
}));

import { VisitChecklist } from "../src/features/visits/VisitChecklist";
import type { Visit, VisitEntry, VisitEntryConflict } from "../src/features/visits/types";

function templateItem(partial: Record<string, unknown>) {
  return {
    key: "k",
    version: 1,
    section_key: "kitchen",
    display_order: 1,
    tier: "quick",
    kind: "check",
    scope: "unit",
    label: "Label",
    help: null,
    value_schema: {},
    is_critical: false,
    ...partial,
  };
}

function entry(partial: Partial<VisitEntry>): VisitEntry {
  return {
    id: "e1",
    visit_id: "v1",
    item_key: "k",
    is_custom: false,
    visit_unit_id: null,
    owner_user_id: null,
    author_user_id: "me",
    value: null,
    answer_text: null,
    note: null,
    prev_entry_id: null,
    created_at: "2026-07-30T10:00:00Z",
    ...partial,
  };
}

let mockTemplate: ReturnType<typeof templateItem>[] = [];
let mockCustom: unknown[] = [];
let mockEntries: VisitEntry[] = [];
let mockConflicts: VisitEntryConflict[] = [];

const visit = {
  id: "v1",
  hunt_id: "h1",
  property_id: "p1",
  created_by: "me",
  scheduled_for: null,
  started_at: "2026-07-30T09:00:00Z",
  ended_at: null,
  cancelled_at: null,
  cancel_reason: null,
  template_version: 1,
  prefilled_from: null,
  created_at: "2026-07-30T08:00:00Z",
  property: { id: "p1", name: "Cedar & Vine", canonical_address: "1412 Cedar Ave" },
  visit_units: [
    {
      id: "unit-a",
      visit_id: "v1",
      label: "4B",
      floor_plan_id: "fp1",
      beds: 2,
      baths: 2,
      unit_group_key: "2-2",
      display_order: 0,
      created_by: "me",
      created_at: "2026-07-30T08:00:00Z",
    },
    {
      id: "unit-b",
      visit_id: "v1",
      label: "2A",
      floor_plan_id: null,
      beds: 1,
      baths: 1,
      unit_group_key: "1-1",
      display_order: 1,
      created_by: "me",
      created_at: "2026-07-30T08:00:00Z",
    },
  ],
};

function render(props: Record<string, unknown> = {}) {
  return renderWithProviders(
    <VisitChecklist visit={visit as unknown as Visit} {...props} />,
  );
}

beforeEach(() => {
  saveEntries.mockReset();
  mockCustom = [];
  mockEntries = [];
  mockConflicts = [];
  mockTemplate = [
    templateItem({ key: "prep_reviews", section_key: "prep", scope: "property", display_order: 1 }),
    templateItem({
      key: "kitchen_stove",
      section_key: "kitchen",
      scope: "unit",
      kind: "fact",
      display_order: 2,
      label: "Stove type",
      value_schema: { type: "enum", options: ["gas", "electric"] },
    }),
    templateItem({
      key: "kitchen_disposal",
      section_key: "kitchen",
      scope: "unit",
      kind: "check",
      display_order: 3,
      label: "Ran the disposal",
    }),
    templateItem({
      key: "hist_bed_bugs",
      section_key: "history",
      scope: "property",
      kind: "question",
      display_order: 4,
      label: "Bed bugs in the last two years?",
      value_schema: { type: "text" },
      is_critical: true,
    }),
    templateItem({
      key: "verdict_noise",
      section_key: "verdict_unit",
      scope: "unit",
      kind: "impression",
      display_order: 5,
      label: "Noise",
      value_schema: { type: "rating", max: 5 },
    }),
  ];
});

/**
 * Reach a section the way a person does now (VC-13): open the picker from the
 * section header and choose from the full list. The 21-section chip strip these
 * tests used to click is gone — that strip is the thing VC-13 removed.
 */
async function openSection(user: ReturnType<typeof userEvent.setup>, title: RegExp) {
  await user.click(screen.getByRole("button", { name: /Jump to a section|of \d+$/ }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: title }));
}

describe("scope drives the unit switcher", () => {
  it("hides the switcher on a property-scoped section and says so", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Before you go/);

    expect(screen.getByText(/recorded/)).toBeInTheDocument();
    expect(screen.getByText(/once for this visit/)).toBeInTheDocument();
    // The switcher would imply a choice that isn't being made.
    expect(screen.queryByRole("button", { name: "4B" })).not.toBeInTheDocument();
  });

  it("shows the switcher on a unit-scoped section and names the active unit", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);

    expect(screen.getByRole("button", { name: "4B" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2A" })).toBeInTheDocument();
    expect(screen.getByText(/Recording into/)).toBeInTheDocument();
  });
});

describe("writes carry the right identity", () => {
  it("sends no unit for a property item", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Before you go/);
    await user.click(screen.getByRole("button", { name: /Label: fine/ }));

    expect(saveEntries).toHaveBeenCalledWith([
      expect.objectContaining({ item_key: "prep_reviews", visit_unit_id: null, value: "ok" }),
    ]);
  });

  it("sends the active unit for a unit item, and follows the switcher", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    await user.click(screen.getByRole("button", { name: /Ran the disposal: fine/ }));
    expect(saveEntries).toHaveBeenLastCalledWith([
      expect.objectContaining({ item_key: "kitchen_disposal", visit_unit_id: "unit-a" }),
    ]);

    await user.click(screen.getByRole("button", { name: "2A" }));
    await user.click(screen.getByRole("button", { name: /Ran the disposal: fine/ }));
    expect(saveEntries).toHaveBeenLastCalledWith([
      expect.objectContaining({ item_key: "kitchen_disposal", visit_unit_id: "unit-b" }),
    ]);
  });

  it("carries prev_entry_id so an offline fork can be detected later", async () => {
    mockEntries = [
      entry({ id: "existing", item_key: "kitchen_disposal", visit_unit_id: "unit-a", value: "ok" }),
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    await user.click(screen.getByRole("button", { name: /Ran the disposal: problem/ }));

    expect(saveEntries).toHaveBeenCalledWith([
      expect.objectContaining({ value: "problem", prev_entry_id: "existing" }),
    ]);
  });

  it("clears by appending a null value rather than deleting", async () => {
    mockEntries = [
      entry({ id: "existing", item_key: "kitchen_disposal", visit_unit_id: "unit-a", value: "ok" }),
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    // Tapping the active state again clears it.
    await user.click(screen.getByRole("button", { name: /Ran the disposal: fine/ }));

    expect(saveEntries).toHaveBeenCalledWith([expect.objectContaining({ value: null })]);
  });
});

describe("mixed-scope sections", () => {
  // Real sections hold both scopes — Building history asks about the building
  // *and* about this unit — so a blanket "recording into 4B" would be false for
  // half of them. Regression guard: this was shipped wrong and caught in the app.
  beforeEach(() => {
    mockTemplate.push(
      templateItem({
        key: "hist_vacancy",
        section_key: "history",
        scope: "unit",
        kind: "question",
        display_order: 4.5,
        label: "How long has this unit been vacant?",
        value_schema: { type: "text" },
      }),
    );
  });

  it("says the section is mixed instead of claiming one scope for all of it", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Building history/);
    expect(screen.getByText(/Mixed —/)).toBeInTheDocument();
    expect(screen.queryByText(/Recording into/)).not.toBeInTheDocument();
  });

  it("tags each item with the scope it actually has", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Building history/);
    // The building question is answered once; the vacancy question per unit.
    expect(screen.getByText("Whole property")).toBeInTheDocument();
    expect(screen.getAllByText("4B").length).toBeGreaterThan(0);
  });

  it("still routes each write to the right identity", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Building history/);

    await user.type(screen.getByRole("textbox", { name: /Answer: Bed bugs/ }), "None");
    await user.click(screen.getAllByRole("button", { name: "Mark asked" })[0]);
    expect(saveEntries).toHaveBeenLastCalledWith([
      expect.objectContaining({ item_key: "hist_bed_bugs", visit_unit_id: null }),
    ]);

    await user.type(screen.getByRole("textbox", { name: /Answer: How long/ }), "3 months");
    await user.click(screen.getAllByRole("button", { name: "Mark asked" })[1]);
    expect(saveEntries).toHaveBeenLastCalledWith([
      expect.objectContaining({ item_key: "hist_vacancy", visit_unit_id: "unit-a" }),
    ]);
  });
});

describe("the question gate", () => {
  it("will not mark a question asked without text", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Building history/);

    const button = screen.getByRole("button", { name: "Mark asked" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Needs an answer first")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: /Answer:/ }), "No incidents");
    expect(screen.getByRole("button", { name: "Mark asked" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Mark asked" }));
    expect(saveEntries).toHaveBeenCalledWith([
      expect.objectContaining({ item_key: "hist_bed_bugs", answer_text: "No incidents" }),
    ]);
  });

  it("shows an answered question as asked", async () => {
    mockEntries = [entry({ id: "a", item_key: "hist_bed_bugs", answer_text: "None on record" })];
    render();
    const user = userEvent.setup();
    await openSection(user, /Building history/);
    expect(screen.getByText("Asked")).toBeInTheDocument();
  });

  it("marks a critical question as such", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Building history/);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });
});

describe("impressions", () => {
  it("labels an impression as the viewer's own", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Verdict — this unit/);
    expect(screen.getByText("Yours")).toBeInTheDocument();
  });

  it("shows the team average once more than one member has rated", async () => {
    mockEntries = [
      entry({ id: "1", item_key: "verdict_noise", visit_unit_id: "unit-a", owner_user_id: "me", value: 2 }),
      entry({ id: "2", item_key: "verdict_noise", visit_unit_id: "unit-a", owner_user_id: "you", value: 4 }),
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Verdict — this unit/);
    expect(screen.getByText(/Team average 3/)).toBeInTheDocument();
  });
});

describe("the red-flag tally", () => {
  beforeEach(() => {
    mockTemplate.push(
      templateItem({
        key: "flag_pests",
        section_key: "red_flags",
        scope: "property",
        kind: "impression",
        display_order: 6,
        label: "Pest traps or droppings visible",
        value_schema: { type: "boolean" },
      }),
    );
  });

  it("names who flagged it, because a lone flag is information not noise", async () => {
    mockEntries = [
      entry({ id: "1", item_key: "flag_pests", owner_user_id: "me", value: true }),
      entry({ id: "2", item_key: "flag_pests", owner_user_id: "you", value: true }),
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Red flags/);
    expect(screen.getByText(/Flagged by/)).toBeInTheDocument();
  });

  it("says nothing at all when nobody has flagged it", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Red flags/);
    expect(screen.queryByText(/Flagged by/)).not.toBeInTheDocument();
  });

  it("shows a flag toggle rather than a rating", async () => {
    render();
    const user = userEvent.setup();
    await openSection(user, /Red flags/);
    await user.click(screen.getByRole("button", { name: /Pest traps or droppings visible/ }));
    expect(saveEntries).toHaveBeenCalledWith([
      expect.objectContaining({ item_key: "flag_pests", value: true, visit_unit_id: null }),
    ]);
  });
});

describe("the depth dial", () => {
  it("hides items above the active tier", async () => {
    mockTemplate.push(
      templateItem({
        key: "kitchen_thorough",
        section_key: "kitchen",
        scope: "unit",
        tier: "thorough",
        // Inside the kitchen run: sections are contiguous by contract (the
        // API-side template test asserts it, and mergeCustomItems preserves it).
        display_order: 3.5,
        label: "Counter space works for how you cook",
      }),
    );
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    expect(screen.queryByText("Counter space works for how you cook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Thorough" }));
    await openSection(user, /Kitchen/);
    expect(screen.getByText("Counter space works for how you cook")).toBeInTheDocument();
  });
});

describe("section restriction before a tour starts", () => {
  it("shows only the sections it is given", () => {
    render({ restrictTo: ["prep"] });
    // The header names the only section there is, and the picker offers no other.
    expect(screen.getByRole("button", { name: /Before you go/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Kitchen/ })).not.toBeInTheDocument();
  });
});

describe("custom items", () => {
  it("renders a per-visit addition, marked as custom", async () => {
    mockCustom = [
      {
        id: "custom-1",
        visit_id: "v1",
        section_key: "kitchen",
        kind: "check",
        scope: "unit",
        label: "Room for the stand mixer",
        created_by: "me",
        created_at: "2026-07-30T10:00:00Z",
      },
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    expect(screen.getByText("Room for the stand mixer")).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();
  });

  it("flags a custom write as custom so the API resolves it correctly", async () => {
    mockCustom = [
      {
        id: "custom-1",
        visit_id: "v1",
        section_key: "kitchen",
        kind: "check",
        scope: "unit",
        label: "Room for the stand mixer",
        created_by: "me",
        created_at: "2026-07-30T10:00:00Z",
      },
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    await user.click(screen.getByRole("button", { name: /Room for the stand mixer: fine/ }));
    expect(saveEntries).toHaveBeenCalledWith([
      expect.objectContaining({ item_key: "custom-1", is_custom: true }),
    ]);
  });
});

describe("progress", () => {
  it("counts answered items per section against the active unit", async () => {
    mockEntries = [
      entry({ id: "1", item_key: "kitchen_disposal", visit_unit_id: "unit-a", value: "ok" }),
    ];
    render();
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    // The header carries the count now, not a chip: "Kitchen", "1 of 2". (The
    // picker row for the same section also names it, hence the first match.)
    expect(screen.getAllByText("1 of 2").length).toBeGreaterThan(0);
  });
});

describe("read-only", () => {
  // A finished tour is a record. Its answers must stay *readable* — greying
  // them out is what made a green tick and a red flag look identical.
  it("keeps the answered check coloured and drops the side nobody pressed", async () => {
    mockEntries = [
      entry({ id: "1", item_key: "kitchen_disposal", visit_unit_id: "unit-a", value: "problem" }),
    ];
    render({ mode: "record" });
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);

    const flag = screen.getByRole("button", { name: /Ran the disposal: problem/ });
    // Not disabled — just not operable. Disabled is what threw the colour away.
    expect(flag).not.toBeDisabled();
    // `light`, not `filled`: the filled variant's text colour is chosen by
    // autoContrast, which flipped between schemes on these earthy hues.
    expect(flag).toHaveAttribute("data-variant", "light");
    expect(
      screen.queryByRole("button", { name: /Ran the disposal: fine/ }),
    ).not.toBeInTheDocument();
  });

  it("says so plainly when a check was never performed", async () => {
    render({ mode: "record" });
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    expect(screen.getByText("Not checked")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Ran the disposal: fine/ }),
    ).not.toBeInTheDocument();
  });

  it("cannot be edited — the control is inert, and refuses to save regardless", async () => {
    mockEntries = [
      entry({ id: "1", item_key: "kitchen_disposal", visit_unit_id: "unit-a", value: "ok" }),
    ];
    render({ mode: "record" });
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    const tick = screen.getByRole("button", { name: /Ran the disposal: fine/ });
    expect(tick.closest("[inert]")).not.toBeNull();
    await user.click(tick);
    expect(saveEntries).not.toHaveBeenCalled();
  });

  it("shows only the Fact option that was chosen", async () => {
    mockEntries = [
      entry({ id: "1", item_key: "kitchen_stove", visit_unit_id: "unit-a", value: "gas" }),
    ];
    render({ mode: "record" });
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    expect(screen.getByText("Gas")).toBeInTheDocument();
    expect(screen.queryByText("Electric")).not.toBeInTheDocument();
  });
});

describe("a cancelled tour is not a record (VC-12)", () => {
  // The two used to render identically, which said the wrong thing about both.
  it("greys the controls out rather than showing a colourless record", async () => {
    render({ mode: "void" });
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);

    const ok = screen.getByRole("button", { name: /Ran the disposal: fine/ });
    const problem = screen.getByRole("button", { name: /Ran the disposal: problem/ });
    // Both sides survive, and both are disabled: nothing was recorded here and
    // nothing ever will be.
    expect(ok).toBeDisabled();
    expect(problem).toBeDisabled();
    expect(screen.queryByText("Not checked")).not.toBeInTheDocument();
  });

  it("still refuses the write even if a control were somehow operated", async () => {
    render({ mode: "void" });
    const user = userEvent.setup();
    await openSection(user, /Kitchen/);
    await user.click(screen.getByRole("button", { name: /Ran the disposal: fine/ }));
    expect(saveEntries).not.toHaveBeenCalled();
  });
});
