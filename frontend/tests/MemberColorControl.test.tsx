import { MantineProvider } from "@mantine/core";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemberColorControl } from "../src/features/collaboration/MemberColorControl";
import { MEMBER_COLOR_TOKENS } from "../src/features/collaboration/memberColors";

function renderControl(
  props: Partial<Parameters<typeof MemberColorControl>[0]> = {},
) {
  const onChange = props.onChange ?? vi.fn();
  render(
    <MantineProvider>
      <MemberColorControl value={null} loading={false} onChange={onChange} {...props} />
    </MantineProvider>,
  );
  return { onChange };
}

const swatch = (name: string) => screen.getByRole("radio", { name });

describe("MemberColorControl", () => {
  it("shows every palette color at once, plus the custom swatch", () => {
    renderControl({ value: "moss" });
    for (const token of MEMBER_COLOR_TOKENS) {
      expect(swatch(token)).toBeInTheDocument();
    }
    expect(swatch("Pick a custom color")).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(MEMBER_COLOR_TOKENS.length + 1);
  });

  it("marks the current token as the checked swatch", () => {
    renderControl({ value: "ochre" });
    expect(swatch("ochre")).toHaveAttribute("aria-checked", "true");
    expect(swatch("moss")).toHaveAttribute("aria-checked", "false");
    expect(swatch("Pick a custom color")).toHaveAttribute("aria-checked", "false");
  });

  it("hides the custom picker for a palette token", () => {
    renderControl({ value: "moss" });
    expect(screen.queryByLabelText("Custom color")).not.toBeInTheDocument();
  });

  it("saves a palette token in one click", () => {
    const { onChange } = renderControl({ value: "moss" });
    fireEvent.click(swatch("plum"));
    expect(onChange).toHaveBeenCalledWith("plum");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("reveals the custom picker without saving when the custom swatch is chosen", () => {
    const { onChange } = renderControl({ value: "moss" });

    fireEvent.click(swatch("Pick a custom color"));

    expect(screen.getByLabelText("Custom color")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("saves a finished custom color change once", () => {
    const { onChange } = renderControl({ value: "#112233" });
    const input = screen.getByLabelText("Custom color");

    fireEvent.change(input, { target: { value: "#AABBCC" } });
    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalledWith("#AABBCC");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("checks the custom swatch — not a token — while a hex value is in use", () => {
    renderControl({ value: "#112233" });
    expect(swatch("Pick a custom color")).toHaveAttribute("aria-checked", "true");
    for (const token of MEMBER_COLOR_TOKENS) {
      expect(swatch(token)).toHaveAttribute("aria-checked", "false");
    }
  });

  it("returns to a palette token and hides the custom picker", () => {
    const { onChange } = renderControl({ value: "#112233" });
    expect(screen.getByLabelText("Custom color")).toBeInTheDocument();

    fireEvent.click(swatch("moss"));

    expect(onChange).toHaveBeenCalledWith("moss");
    expect(screen.queryByLabelText("Custom color")).not.toBeInTheDocument();
  });

  it("disables every swatch while a save is in flight", () => {
    renderControl({ value: "moss", loading: true });
    for (const control of screen.getAllByRole("radio")) {
      expect(control).toBeDisabled();
    }
  });
});
