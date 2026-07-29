// Settings frame behavior (P3-16): the rail selects, and the save bar exists
// only when something is dirty — and says what.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IconHome, IconUserCircle } from "@tabler/icons-react";
import { describe, expect, it, vi } from "vitest";

import {
  SettingsSaveBar,
  SettingsShell,
  type SettingsTab,
} from "../src/components/SettingsShell";
import { renderWithProviders } from "./testUtils";

const TABS: SettingsTab[] = [
  { value: "hunt", label: "Hunt", description: "Scoring, people, name", icon: <IconHome /> },
  { value: "profile", label: "Your profile", description: "Name, color, role", icon: <IconUserCircle /> },
];

describe("SettingsShell", () => {
  it("renders each tab with its second line and marks the active one", () => {
    renderWithProviders(
      <SettingsShell tabs={TABS} active="hunt" onSelect={() => {}}>
        <p>panel</p>
      </SettingsShell>,
    );

    expect(screen.getByRole("tab", { name: /Hunt/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Your profile/ })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    // The subtitle is what makes two tabs navigable rather than thin.
    expect(screen.getByText("Scoring, people, name")).toBeInTheDocument();
    expect(screen.getByText("panel")).toBeInTheDocument();
  });

  it("reports the selected tab by value", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <SettingsShell tabs={TABS} active="hunt" onSelect={onSelect}>
        <p>panel</p>
      </SettingsShell>,
    );

    await user.click(screen.getByRole("tab", { name: /Your profile/ }));
    expect(onSelect).toHaveBeenCalledWith("profile");
  });
});

describe("SettingsSaveBar", () => {
  it("renders nothing when the panel is clean", () => {
    renderWithProviders(
      <SettingsSaveBar dirtyLabels={[]} onSave={() => {}} onDiscard={() => {}} />,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("names what changed rather than only that something did", () => {
    renderWithProviders(
      <SettingsSaveBar
        dirtyLabels={["cost estimates", "cats"]}
        onSave={() => {}}
        onDiscard={() => {}}
      />,
    );
    expect(screen.getByText("2 unsaved changes")).toBeInTheDocument();
    expect(screen.getByText(/cost estimates, cats/)).toBeInTheDocument();
  });

  it("uses the singular for one change", () => {
    renderWithProviders(
      <SettingsSaveBar dirtyLabels={["color"]} onSave={() => {}} onDiscard={() => {}} />,
    );
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();
  });

  it("saves and discards", async () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <SettingsSaveBar dirtyLabels={["color"]} onSave={onSave} onDiscard={onDiscard} />,
    );

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(onSave).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });
});
