import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StarRating } from "../src/features/collaboration/StarRating";

describe("StarRating", () => {
  it("shows the rating value to assistive tech", () => {
    render(
      <MantineProvider>
        <StarRating value={4.5} />
      </MantineProvider>,
    );
    expect(screen.getByLabelText("4.5 of 5")).toBeInTheDocument();
  });

  it("clamps values outside 0..5", () => {
    const { container: over } = render(
      <MantineProvider>
        <StarRating value={7} />
      </MantineProvider>,
    );
    const { container: max } = render(
      <MantineProvider>
        <StarRating value={5} />
      </MantineProvider>,
    );
    const clipPaths = (root: HTMLElement) =>
      Array.from(root.querySelectorAll(".mantine-Rating-symbolBody")).map((el) =>
        el.getAttribute("style"),
      );
    expect(clipPaths(over)).toEqual(clipPaths(max));
  });

  it("accepts a custom fill color", () => {
    render(
      <MantineProvider>
        <StarRating value={3} color="grape" />
      </MantineProvider>,
    );
    expect(screen.getByLabelText("3 of 5")).toBeInTheDocument();
  });
});
