import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatingDots } from "./RatingDots";

describe("RatingDots", () => {
  it("renders one member-colored dot per rating", () => {
    render(
      <MantineProvider>
        <RatingDots
          ratings={[{ hunt_listing_id: "l", user_id: "u", rating: 4 }]}
          members={[{ hunt_id: "h", user_id: "u", role: "member", color: "#123456", display_name: "Yusuf" }]}
        />
      </MantineProvider>,
    );
    expect(screen.getByLabelText("4 of 5")).toHaveStyle({ background: "#123456" });
  });
});
