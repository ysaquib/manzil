// Shared table pagination: the window, and the two ways it can strand you.
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { TablePagination, usePagedRows } from "../src/components/TablePagination";
import { renderWithProviders } from "./testUtils";

/** Mantine hangs the aria-label on a hidden node too, so match the input. */
const pageSizeInput = () => screen.getByRole("combobox", { name: "Rows per page" });

/** A list whose length the test can change, the way a filter would. */
function Harness({ initial = 120 }: { initial?: number }) {
  const [count, setCount] = useState(initial);
  const rows = Array.from({ length: count }, (_, index) => `row ${index + 1}`);
  const paged = usePagedRows(rows, `test-${initial}`);
  return (
    <div>
      <button type="button" onClick={() => setCount(3)}>
        shrink
      </button>
      <ul>
        {paged.items.map((row) => (
          <li key={row}>{row}</li>
        ))}
      </ul>
      <TablePagination state={paged} noun="rows" />
    </div>
  );
}

describe("TablePagination", () => {
  it("shows the first 50 rows and nothing past them", () => {
    renderWithProviders(<Harness />);

    expect(screen.getByText("row 1")).toBeInTheDocument();
    expect(screen.getByText("row 50")).toBeInTheDocument();
    expect(screen.queryByText("row 51")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1–50 of 120 rows")).toBeInTheDocument();
  });

  it("moves the window with the page", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "3" }));

    expect(screen.getByText("row 101")).toBeInTheDocument();
    expect(screen.queryByText("row 100")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 101–120 of 120 rows")).toBeInTheDocument();
  });

  it("returns to row 1 when the page size changes, not to wherever the offset lands", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "3" }));
    await user.click(pageSizeInput());
    await user.click(await screen.findByText("250 / page"));

    expect(screen.getByText("Showing 1–120 of 120 rows")).toBeInTheDocument();
    expect(screen.getByText("row 120")).toBeInTheDocument();
  });

  it("walks back to a real page when a filter shrinks the list underneath it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness initial={200} />);

    await user.click(screen.getByRole("button", { name: "4" }));
    expect(screen.getByText("row 151")).toBeInTheDocument();

    // The list drops to three rows — page 4 no longer exists.
    await user.click(screen.getByRole("button", { name: "shrink" }));

    await waitFor(() =>
      expect(screen.getByText("Showing 1–3 of 3 rows")).toBeInTheDocument(),
    );
    expect(screen.getByText("row 1")).toBeInTheDocument();
  });

  it("keeps the rows-per-page control on a single page, since that is how you get more", () => {
    renderWithProviders(<Harness initial={4} />);

    expect(pageSizeInput()).toBeInTheDocument();
    // Page numbers, which would do nothing here, are the part that goes.
    expect(screen.queryByRole("button", { name: "2" })).not.toBeInTheDocument();
  });
});
