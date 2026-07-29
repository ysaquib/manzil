// Role → permissions, transcribed from DESIGN §4.2's matrix (P3-16).
//
// This is presentation only: RLS plus the API mirror are the enforcement
// (frontend/AGENTS.md). What it buys is the standing answer to "why can't I do
// that?" — the question role-gating creates and which, until now, the app only
// answered by letting a save fail.
//
// Kept pure and separate from the card that renders it so the matrix can be
// asserted directly against §4.2 in tests. When §4.2 changes, this changes with
// it in the same commit.
import type { HuntMember } from "./api";

export type HuntRole = HuntMember["role"];

export interface RolePermission {
  label: string;
  /** Qualifier for rows §4.2 scopes rather than grants outright. */
  scope?: string;
}

export interface RolePermissions {
  role: HuntRole;
  roleLabel: string;
  permitted: RolePermission[];
  withheld: RolePermission[];
  /** Sentence shown when a role withholds nothing. */
  withheldNote?: string;
}

export const ROLE_LABEL: Record<HuntRole, string> = {
  owner: "Owner",
  curator: "Curator",
  member: "Member",
};

const EVERYONE: RolePermission[] = [
  { label: "See every listing, score, and the Rubric" },
  { label: "Submit listings" },
  { label: "Comment and rate" },
  { label: "Set your own color and display name" },
  { label: "View task history" },
  { label: "Cancel and retry jobs", scope: "that you started" },
];

const STEWARDSHIP: RolePermission[] = [
  { label: "Override extracted values" },
  { label: "Correct fees and utilities" },
  { label: "Answer checkpoints" },
  { label: "Set Interest Status and visited" },
];

const OWNER_ONLY: RolePermission[] = [
  { label: "Edit the Rubric" },
  { label: "Change hunt settings" },
  { label: "Invite people and manage roles" },
  { label: "Remove members" },
  { label: "Delete listings" },
  { label: "Manage anyone's jobs" },
  { label: "Archive the hunt" },
];

export function rolePermissions(role: HuntRole): RolePermissions {
  if (role === "owner") {
    return {
      role,
      roleLabel: ROLE_LABEL.owner,
      permitted: [
        ...EVERYONE,
        ...STEWARDSHIP.map((permission) => ({ ...permission, scope: "on any listing" })),
        ...OWNER_ONLY,
      ],
      withheld: [],
      withheldNote:
        "Nothing — Owner is the highest role in a hunt. Only one person holds it, and handing it over is in the danger zone below.",
    };
  }

  if (role === "curator") {
    return {
      role,
      roleLabel: ROLE_LABEL.curator,
      permitted: [
        ...EVERYONE,
        ...STEWARDSHIP.map((permission) => ({ ...permission, scope: "on any listing" })),
      ],
      withheld: OWNER_ONLY,
    };
  }

  return {
    role,
    roleLabel: ROLE_LABEL.member,
    permitted: [
      ...EVERYONE,
      ...STEWARDSHIP.filter((permission) => permission.label !== "Set Interest Status and visited")
        .map((permission) => ({ ...permission, scope: "on listings you added" })),
    ],
    withheld: [
      ...STEWARDSHIP.filter((permission) => permission.label !== "Set Interest Status and visited")
        .map((permission) => ({ ...permission, scope: "on someone else's listing" })),
      { label: "Set Interest Status and visited" },
      ...OWNER_ONLY,
    ],
  };
}
