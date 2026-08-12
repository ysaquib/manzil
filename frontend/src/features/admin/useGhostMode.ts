// Ghost mode (AD-4, DESIGN §4.2, §20 v3.39).
//
// Non-membership still enters Ghost View automatically. A member can enter it
// only through the Admin Hunts dashboard, whose navigation state is captured by
// `GhostModeProvider` for the lifetime of this Hunt route. It is intentionally
// not a query parameter: ordinary Hunt links remain ordinary, and the admin
// context cannot leak into a copied URL.
//
// This is UX. Every write a ghost cannot make is refused by RLS, whose write
// policies were deliberately left untouched by AD-4's read predicate.
import { createContext, createElement, type ReactNode, useContext, useState } from "react";
import { useLocation } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { useMembers } from "../collaboration/api";
import { useHunt } from "../hunts/api";
import { useAdminIdentity } from "./api";

export interface GhostMode {
  /** `undefined` until membership is known — never assume "member". */
  isGhost: boolean | undefined;
  /** True once the answer is settled either way. */
  resolved: boolean;
}

const AdminGhostEntryContext = createContext(false);

export function GhostModeProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  // Capture once. Child navigation replaces location state, but the explicit
  // admin mode must remain until this Hunt route is left or switched.
  const [adminGhostEntry] = useState(
    () => (location.state as { adminGhost?: unknown } | null)?.adminGhost === true,
  );
  return createElement(AdminGhostEntryContext.Provider, { value: adminGhostEntry }, children);
}

export function useGhostMode(huntId: string | undefined): GhostMode {
  const adminGhostEntry = useContext(AdminGhostEntryContext);
  const { session } = useAuth();
  const admin = useAdminIdentity();
  const members = useMembers(huntId ?? "");
  const hunt = useHunt(huntId ?? "");

  if (!huntId || admin.isPending || members.isPending || hunt.isPending) {
    return { isGhost: undefined, resolved: false };
  }

  // Not an admin: ordinary member, ordinary rules, nothing to decide.
  if (!admin.data?.is_site_admin) {
    return { isGhost: false, resolved: true };
  }

  const userId = session?.user.id;
  const isMember = (members.data ?? []).some((member) => member.user_id === userId);

  // An explicit Admin-dashboard entry opts into audited support mode even for
  // a member. Everywhere else, genuine membership wins — including archived
  // Hunts, so an Owner can reach the ordinary restore controls.
  return { isGhost: adminGhostEntry || !isMember, resolved: true };
}

/** Route an ordinary Hunt mutation through the audited Ghost View surface. */
export function useGhostMutationPath(huntId: string): (path: string) => string {
  const { isGhost } = useGhostMode(huntId);
  return (path: string) => isGhost ? path.replace("/v1/", "/v1/admin/ghost/") : path;
}
