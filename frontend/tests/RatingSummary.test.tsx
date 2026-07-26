import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HuntMember, Rating } from "../src/features/collaboration/api";
import {
  averageRating,
  formatAverage,
  RatingSummary,
} from "../src/features/collaboration/RatingSummary";

const member = (user_id: string, display_name: string, color: string | null): HuntMember =>
  ({ hunt_id: "h", user_id, role: "member", color, display_name }) as HuntMember;

const rating = (user_id: string, value: number): Rating =>
  ({ hunt_listing_id: "l", unit_group_key: "2-1", user_id, rating: value }) as Rating;

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe("averageRating", () => {
  it("averages the ratings present", () => {
    expect(averageRating([rating("a", 4), rating("b", 5)])).toBe(4.5);
  });

  it("is null when nobody has rated", () => {
    expect(averageRating([])).toBeNull();
  });
});

describe("formatAverage", () => {
  it("drops a trailing .0", () => {
    expect(formatAverage(4)).toBe("4");
  });

  it("keeps one decimal otherwise", () => {
    expect(formatAverage(4.25)).toBe("4.3");
    expect(formatAverage(3.5)).toBe("3.5");
  });
});

describe("RatingSummary", () => {
  const members = [member("a", "Yusuf", "plum"), member("b", "Sam", "moss")];

  it("shows the average and one dot per member who rated", () => {
    wrap(
      <RatingSummary ratings={[rating("a", 4), rating("b", 5)]} members={members} />,
    );
    expect(screen.getByLabelText("average 4.5 of 5")).toBeInTheDocument();
    expect(screen.getByLabelText("Yusuf: 4 of 5")).toBeInTheDocument();
    expect(screen.getByLabelText("Sam: 5 of 5")).toBeInTheDocument();
  });

  it("says nothing rather than zero when nobody has rated", () => {
    wrap(<RatingSummary ratings={[]} members={members} />);
    expect(screen.getByLabelText("no ratings yet")).toBeInTheDocument();
  });

  it("shows a comment count when there are comments", () => {
    wrap(<RatingSummary ratings={[rating("a", 4)]} members={members} commentCount={3} />);
    expect(screen.getByLabelText("3 comments")).toBeInTheDocument();
  });

  it("hides the comment count entirely at zero, so quiet rows stay quiet", () => {
    wrap(<RatingSummary ratings={[rating("a", 4)]} members={members} commentCount={0} />);
    expect(screen.queryByLabelText(/comments/)).not.toBeInTheDocument();
  });
});
