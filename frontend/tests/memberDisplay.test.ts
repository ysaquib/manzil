import { describe, expect, it } from "vitest";

import type { HuntMember } from "../src/features/collaboration/api";
import { memberDisplayName, memberDisplayNameMap } from "../src/features/collaboration/memberDisplay";

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
    expect(memberDisplayName(members, "uuid-missing")).toBe("Member");
  });
});

describe("memberDisplayNameMap", () => {
  it("maps every member to a human label", () => {
    const map = memberDisplayNameMap(members);
    expect(map.get("uuid-yusuf")).toBe("Yusuf");
    expect(map.get("uuid-other")).toBe("Member");
  });
});
