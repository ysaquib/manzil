// The role matrix is a transcription of DESIGN §4.2, so it is asserted against
// that table rather than against itself (P3-16).
import { describe, expect, it } from "vitest";

import { rolePermissions, ROLE_LABEL } from "../src/features/collaboration/rolePermissions";

const labels = (permissions: { label: string }[]) => permissions.map((p) => p.label);

describe("rolePermissions", () => {
  it("uses the hunt's own role vocabulary", () => {
    expect(ROLE_LABEL).toEqual({ owner: "Owner", curator: "Curator", member: "Member" });
  });

  it("gives the Owner every permission and withholds nothing", () => {
    const owner = rolePermissions("owner");
    expect(owner.withheld).toEqual([]);
    expect(owner.withheldNote).toMatch(/highest role/i);
    // §4.2: the Owner-only column.
    expect(labels(owner.permitted)).toEqual(
      expect.arrayContaining([
        "Edit the Rubric",
        "Change hunt settings",
        "Invite people and manage roles",
        "Remove members",
        "Delete listings",
        "Archive the hunt",
      ]),
    );
  });

  it("gives a Curator stewardship over any listing but nothing owner-only", () => {
    const curator = rolePermissions("curator");
    const permitted = labels(curator.permitted);
    expect(permitted).toEqual(
      expect.arrayContaining([
        "Override extracted values",
        "Answer checkpoints",
        "Set Interest Status and visited",
      ]),
    );
    // §4.2 gives the Curator these on *any* listing, not just their own.
    for (const permission of curator.permitted) {
      if (permission.label === "Override extracted values") {
        expect(permission.scope).toBe("on any listing");
      }
    }
    expect(labels(curator.withheld)).toEqual(
      expect.arrayContaining(["Edit the Rubric", "Change hunt settings", "Remove members"]),
    );
    expect(permitted).not.toContain("Edit the Rubric");
  });

  it("scopes a Member's stewardship to their own listings and withholds the rest", () => {
    const member = rolePermissions("member");
    const own = member.permitted.find((p) => p.label === "Override extracted values");
    expect(own?.scope).toBe("on listings you added");

    const withheldLabels = labels(member.withheld);
    // The same capability appears on both sides with different scopes — that is
    // §4.2's "own listings" row, and it is the distinction a Member needs.
    expect(withheldLabels).toContain("Override extracted values");
    expect(
      member.withheld.find((p) => p.label === "Override extracted values")?.scope,
    ).toBe("on someone else's listing");

    // §4.2: Interest Status is read-only for a Member at any scope.
    expect(labels(member.permitted)).not.toContain("Set Interest Status and visited");
    expect(withheldLabels).toContain("Set Interest Status and visited");
  });

  it("lets every role comment, rate, and submit listings", () => {
    for (const role of ["owner", "curator", "member"] as const) {
      const permitted = labels(rolePermissions(role).permitted);
      expect(permitted).toContain("Submit listings");
      expect(permitted).toContain("Comment and rate");
      expect(permitted).toContain("See every listing, score, and the Rubric");
    }
  });
});
