import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { HuntContributor, HuntMember } from "../src/features/collaboration/api";

vi.mock("../src/features/collaboration/api", async (orig) => ({
  ...(await orig<typeof import("../src/features/collaboration/api")>()),
  useRatings: () => ({
    data: [
      { hunt_listing_id: "l", unit_group_key: "g", user_id: "u1", rating: 4 },
      { hunt_listing_id: "l", unit_group_key: "g", user_id: "u2", rating: 4.5 },
    ],
  }),
}));

import { TeamRatings } from "../src/features/collaboration/TeamRatings";

function renderTeam({
  members,
  contributors,
}: {
  members: HuntMember[];
  contributors?: HuntContributor[];
}) {
  return render(
    <MantineProvider>
      <TeamRatings
        listingId="l"
        unitGroupKey="g"
        members={members}
        contributors={contributors}
      />
    </MantineProvider>,
  );
}

const member = (over: Partial<HuntMember> & Pick<HuntMember, "user_id" | "display_name">): HuntMember => ({
  hunt_id: "h",
  role: "member",
  color: null,
  ...over,
});

describe("TeamRatings", () => {
  it("lists members' ratings, a not-rated state, and the average", () => {
    renderTeam({
      members: [
        member({ user_id: "u1", display_name: "Amara" }),
        member({ user_id: "u2", display_name: "Maya" }),
        member({ user_id: "u3", display_name: "Dev" }),
      ],
    });
    expect(screen.getByText("Amara")).toBeInTheDocument();
    expect(screen.getByText("Not rated yet")).toBeInTheDocument(); // Dev
    expect(screen.getByText(/avg 4\.3/)).toBeInTheDocument(); // (4 + 4.5)/2 = 4.25 → 4.3
  });

  it("keeps a departed rater without listing them as a current member", () => {
    renderTeam({
      members: [member({ user_id: "u1", display_name: "Amara" })],
      contributors: [
        { user_id: "u2", display_name: "Maya", color: "plum", is_former: true },
      ],
    });
    expect(screen.getByText("Former User (Maya)")).toBeInTheDocument();
    expect(screen.queryByText("Maya", { exact: true })).not.toBeInTheDocument();
  });
});
