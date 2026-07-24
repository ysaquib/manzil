import { MantineProvider } from "@mantine/core";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StarRating } from "../src/features/collaboration/StarRating";

describe("StarRating", () => {
  it("fills to the rating fraction", () => {
    const { container } = render(
      <MantineProvider>
        <StarRating value={4.5} />
      </MantineProvider>,
    );
    const fill = container.querySelector("[data-fill]") as HTMLElement;
    expect(fill.style.width).toBe("90%");
  });

  it("clamps values outside 0..5", () => {
    const { container } = render(
      <MantineProvider>
        <StarRating value={7} />
      </MantineProvider>,
    );
    const fill = container.querySelector("[data-fill]") as HTMLElement;
    expect(fill.style.width).toBe("100%");
  });

  it("applies a custom fill color when given", () => {
    const { container } = render(
      <MantineProvider>
        <StarRating value={3} color="var(--mantine-color-grape-6)" />
      </MantineProvider>,
    );
    const fill = container.querySelector("[data-fill]") as HTMLElement;
    expect(fill.style.color).toBe("var(--mantine-color-grape-6)");
  });
});
