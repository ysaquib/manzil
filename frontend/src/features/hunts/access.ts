import { useAuth } from "../../auth/useAuth";
import { useAdminIdentity } from "../admin/api";
import { useGhostMode } from "../admin/useGhostMode";
import { useHunt } from "./api";

export type HuntReadOnlyReason = "archived" | "locked" | null;

export function useHuntAccess(huntId: string) {
  const { session } = useAuth();
  const hunt = useHunt(huntId);
  const admin = useAdminIdentity();
  const ghost = useGhostMode(huntId);
  const archived = Boolean(hunt.data?.archived_at);
  const locked = Boolean(hunt.data?.locked_at);
  const isSiteAdmin = Boolean(admin.data?.is_site_admin);
  const isOwner = hunt.data?.owner_id === session?.user.id;
  const adminArchivedOverride = archived && isSiteAdmin && !locked;
  const reason = locked
    ? "A Site Admin locked this Hunt."
    : archived && !isSiteAdmin
      ? "Archived Hunts cannot be changed."
      : null;

  return {
    hunt: hunt.data,
    archived,
    locked,
    isOwner,
    isSiteAdmin,
    isGhost: ghost.isGhost,
    adminArchivedOverride,
    canMutate: !locked && (!archived || isSiteAdmin),
    canManageLifecycle: !locked && (Boolean(isOwner) || isSiteAdmin),
    state: (locked ? "locked" : archived ? "archived" : null) as HuntReadOnlyReason,
    readOnlyReason: (locked ? "locked" : archived && !isSiteAdmin ? "archived" : null) as HuntReadOnlyReason,
    reason,
    isLoading: hunt.isLoading || admin.isPending || !ghost.resolved,
  };
}
