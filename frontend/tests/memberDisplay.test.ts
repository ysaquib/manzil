import { describe, expect, it } from "vitest";

import type { HuntMember } from "../src/features/collaboration/api";
import {
  contributorColor,
  contributorDisplayName,
  memberDisplayName,
  memberDisplayNameMap,
} from "../src/features/collaboration/memberDisplay";

const members: HuntMember[] = [
  {
    hunt_id: "h1",
    user_id: "uuid-yusuf",
    role: "owner",
    color: "moss",
    display_name: "Yusuf",
  },
  {
    hunt_id: "h1",
    user_id: "uuid-other",
    role: "member",
    color: null,
    display_name: null,
  },
];

describe("memberDisplayName", () => {
  it("returns the hunt display name when set", () => {
    expect(memberDisplayName(members, "uuid-yusuf")).toBe("Yusuf");
  });

  it("never returns a raw user id", () => {
    expect(memberDisplayName(members, "uuid-other")).toBe("Member");
    expect(memberDisplayName(members, "uuid-missing")).toBe("Former User");
  });
});

describe("memberDisplayNameMap", () => {
  it("maps every member to a human label", () => {
    const map = memberDisplayNameMap(members);
    expect(map.get("uuid-yusuf")).toBe("Yusuf");
    expect(map.get("uuid-other")).toBe("Member");
  });
});

describe("former contributor attribution", () => {
  const former = {
    user_id: "uuid-former",
    display_name: "Sam",
    color: null,
    is_former: true,
  };

  it("names the person without presenting them as a current Member", () => {
    expect(contributorDisplayName(former)).toBe("Former User (Sam)");
    expect(memberDisplayName([former], former.user_id)).toBe("Former User (Sam)");
  });

  it("uses a neutral grey instead of the person's old member color", () => {
    expect(contributorColor({ ...former, color: "plum" })).toBe(
      "var(--mantine-color-gray-5)",
    );
  });

  it("does not present a legacy generic tombstone as a Member", () => {
    expect(contributorDisplayName({ ...former, display_name: "Member" })).toBe(
      "Former User",
    );
  });
});
