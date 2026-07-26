import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CatalogEntry } from "../src/features/rubric/api";
import { CriterionPicker } from "../src/features/rubric/CriterionPicker";

const entry = (key: string, label: string, category = "unit"): CatalogEntry => ({
  key,
  label,
  category,
  domain: "rent",
  fact_scope: "floor_plan",
  value_schema: { type: "number" },
  default_options: [],
  extraction_hint: "",
  requires_tool: null,
  refresh_class: "static",
});

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe("CriterionPicker", () => {
  it("offers one button per unscored criterion", () => {
    wrap(
      <CriterionPicker
        entries={[entry("sqft", "Square footage"), entry("parking", "Parking")]}
        onEnable={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Square footage" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Parking" })).toBeInTheDocument();
  });

  it("enables the criterion it was clicked for", async () => {
    const onEnable = vi.fn();
    const sqft = entry("sqft", "Square footage");
    wrap(<CriterionPicker entries={[sqft, entry("parking", "Parking")]} onEnable={onEnable} />);

    await userEvent.click(screen.getByRole("button", { name: "Square footage" }));

    expect(onEnable).toHaveBeenCalledTimes(1);
    expect(onEnable).toHaveBeenCalledWith(sqft);
  });

  it("renders nothing when every criterion in the category is scored", () => {
    wrap(<CriterionPicker entries={[]} onEnable={vi.fn()} />);
    expect(screen.queryByText(/not scored/i)).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
