// AD-4: ghost mode is *derived*, never declared.
//
// The failure this guards against is subtle and one-directional: if the answer
// defaults to "member" while membership is still loading, a Site Admin flashes
// onto somebody else's tour in Presence before the correction lands. So the
// hook reports `undefined` until it knows, and every consumer treats
// "not yet known" as "not a member".
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useAuth = vi.hoisted(() => vi.fn());
const useMembers = vi.hoisted(() => vi.fn());
const useAdminIdentity = vi.hoisted(() => vi.fn());

vi.mock("../src/auth/useAuth", () => ({ useAuth }));
vi.mock("../src/features/collaboration/api", () => ({ useMembers }));
vi.mock("../src/features/admin/api", () => ({ useAdminIdentity }));

import { useGhostMode } from "../src/features/admin/useGhostMode";

const ME = "me-1";

function setup({
  isAdmin,
  members,
  pending = false,
}: {
  isAdmin: boolean;
  members: string[];
  pending?: boolean;
}) {
  useAuth.mockReturnValue({ session: { user: { id: ME } } });
  useAdminIdentity.mockReturnValue({
    isPending: false,
    data: { is_site_admin: isAdmin },
  });
  useMembers.mockReturnValue({
    isPending: pending,
    data: pending ? undefined : members.map((user_id) => ({ user_id })),
  });
}

describe("useGhostMode", () => {
  beforeEach(() => {
    useAuth.mockReset();
    useMembers.mockReset();
    useAdminIdentity.mockReset();
  });

  it("is undefined while membership is still unknown", () => {
    setup({ isAdmin: true, members: [], pending: true });
    const { result } = renderHook(() => useGhostMode("h1"));

    // Not `false`. A consumer that treats undefined as "member" would announce
    // an admin into a tour they are only watching.
    expect(result.current.isGhost).toBeUndefined();
    expect(result.current.resolved).toBe(false);
  });

  it("is a ghost when an admin is not a member of this Hunt", async () => {
    setup({ isAdmin: true, members: ["someone-else"] });
    const { result } = renderHook(() => useGhostMode("h1"));

    await waitFor(() => expect(result.current.resolved).toBe(true));
    expect(result.current.isGhost).toBe(true);
  });

  it("is NOT a ghost when the admin genuinely belongs to the Hunt", async () => {
    // §4.2's conditional clause: an admin who is a real member is an ordinary
    // member there — no banner, no suppression, nothing.
    setup({ isAdmin: true, members: [ME, "someone-else"] });
    const { result } = renderHook(() => useGhostMode("h1"));

    await waitFor(() => expect(result.current.resolved).toBe(true));
    expect(result.current.isGhost).toBe(false);
  });

  it("is never a ghost for an ordinary user, member or not", async () => {
    setup({ isAdmin: false, members: ["someone-else"] });
    const { result } = renderHook(() => useGhostMode("h1"));

    await waitFor(() => expect(result.current.resolved).toBe(true));
    expect(result.current.isGhost).toBe(false);
  });

  it("stays unresolved without a Hunt", () => {
    setup({ isAdmin: true, members: [] });
    const { result } = renderHook(() => useGhostMode(undefined));

    expect(result.current.isGhost).toBeUndefined();
  });
});
