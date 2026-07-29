// Drawer state ↔ URL (P3-16). The pure helpers are asserted directly; the hook
// runs inside a real router, and push-versus-replace is read off
// `useNavigationType` — the router's own account of what it just did — rather
// than from a mocked `setSearchParams`.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router-dom";
import { describe, expect, it } from "vitest";

import {
  drawerParams,
  readSelection,
  useDrawerRoute,
  withoutDrawer,
} from "../src/features/listings/drawerRoute";

describe("drawer param helpers", () => {
  it("omits the group when a listing has only one unit group", () => {
    expect(drawerParams("lst_1", null)).toEqual({ listing: "lst_1" });
    expect(drawerParams("lst_1", "2-1")).toEqual({ listing: "lst_1", group: "2-1" });
  });

  it("reads a selection back, or null when no drawer is addressed", () => {
    expect(readSelection(new URLSearchParams("?score=70"))).toBeNull();
    expect(readSelection(new URLSearchParams("?listing=lst_1"))).toEqual({
      listingId: "lst_1",
      groupKey: null,
    });
    expect(readSelection(new URLSearchParams("?listing=lst_1&group=2-1"))).toEqual({
      listingId: "lst_1",
      groupKey: "2-1",
    });
  });

  it("strips only drawer params, leaving filters and sort untouched", () => {
    const stripped = withoutDrawer(
      new URLSearchParams("?score=70&listing=lst_1&group=2-1&plan=fp_9&tab=criteria&city=Ypsi"),
    );
    expect(stripped.toString()).toBe("score=70&city=Ypsi");
  });
});

function Probe() {
  const drawer = useDrawerRoute();
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <div>
      <span data-testid="search">{location.search}</span>
      <span data-testid="nav-type">{navigationType}</span>
      <span data-testid="selection">{JSON.stringify(drawer.selection)}</span>
      <span data-testid="render">{JSON.stringify(drawer.renderSelection)}</span>
      <button onClick={() => drawer.open("lst_1", "2-1")}>open</button>
      <button onClick={() => drawer.close()}>close</button>
      <button onClick={() => drawer.setTab("criteria")}>tab</button>
      <button onClick={() => drawer.onExited()}>exited</button>
    </div>
  );
}

function renderProbe(initial = "/h/h1?score=70") {
  return render(
    <MemoryRouter initialEntries={["/start", initial]} initialIndex={1}>
      <Routes>
        <Route path="/start" element={<span>start</span>} />
        <Route path="/h/:huntId" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("useDrawerRoute", () => {
  it("opens into the URL while preserving existing filters", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "open" }));

    expect(screen.getByTestId("search").textContent).toBe("?score=70&listing=lst_1&group=2-1");
    expect(JSON.parse(screen.getByTestId("selection").textContent!)).toEqual({
      listingId: "lst_1",
      groupKey: "2-1",
    });
  });

  it("restores the drawer from a cold URL — the shared-link case", () => {
    renderProbe("/h/h1?listing=lst_8f21&group=2-1&tab=criteria");
    expect(JSON.parse(screen.getByTestId("selection").textContent!)).toEqual({
      listingId: "lst_8f21",
      groupKey: "2-1",
    });
  });

  it("closes by clearing the params and keeps rendering until the exit finishes", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "open" }));
    await user.click(screen.getByRole("button", { name: "close" }));

    expect(screen.getByTestId("search").textContent).toBe("?score=70");
    expect(screen.getByTestId("selection").textContent).toBe("null");
    // The closing drawer still has content to animate out with.
    expect(JSON.parse(screen.getByTestId("render").textContent!)).toEqual({
      listingId: "lst_1",
      groupKey: "2-1",
    });

    await user.click(screen.getByRole("button", { name: "exited" }));
    expect(screen.getByTestId("render").textContent).toBe("null");
  });

  it("pushes on open, so Back is what closes the drawer", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "open" }));

    expect(screen.getByTestId("search").textContent).toBe("?score=70&listing=lst_1&group=2-1");
    // A pushed entry is the whole reason Back closes the drawer instead of
    // leaving the hunt.
    expect(screen.getByTestId("nav-type").textContent).toBe("PUSH");
  });

  it("replaces on tab change, so Back does not walk out through tabs", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "open" }));
    await user.click(screen.getByRole("button", { name: "tab" }));

    expect(screen.getByTestId("search").textContent).toBe(
      "?score=70&listing=lst_1&group=2-1&tab=criteria",
    );
    expect(screen.getByTestId("nav-type").textContent).toBe("REPLACE");
  });

  it("replaces on close, so Back cannot resurrect the drawer just dismissed", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "open" }));
    await user.click(screen.getByRole("button", { name: "close" }));

    expect(screen.getByTestId("search").textContent).toBe("?score=70");
    expect(screen.getByTestId("nav-type").textContent).toBe("REPLACE");
  });
});
