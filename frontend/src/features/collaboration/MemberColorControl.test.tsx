import { MantineProvider } from "@mantine/core";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemberColorControl } from "./MemberColorControl";

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

function openPalette() {
  fireEvent.click(screen.getByRole("combobox", { name: "Palette color" }));
}

function chooseOption(value: string) {
  openPalette();
  const option = screen.getByRole("option", {
    name: new RegExp(value, "i"),
    hidden: true,
  });
  fireEvent.click(option);
}

describe("MemberColorControl", () => {
  it("hides the custom picker for a palette token", () => {
    renderControl({ value: "dusk" });
    expect(screen.queryByLabelText("Custom color")).not.toBeInTheDocument();
  });

  it("reveals the custom picker without saving when Custom color is selected", () => {
    const { onChange } = renderControl({ value: "dusk" });

    chooseOption("Custom color");

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

  it("saves a palette token and hides the custom picker", () => {
    const { onChange } = renderControl({ value: "#112233" });

    expect(screen.getByLabelText("Custom color")).toBeInTheDocument();

    chooseOption("moss");

    expect(onChange).toHaveBeenCalledWith("moss");
    expect(screen.queryByLabelText("Custom color")).not.toBeInTheDocument();
  });
});
