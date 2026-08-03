// Ghost mode (AD-4, DESIGN §4.2, §20 v3.39).
//
// **Derived from non-membership, never from URL state.** A `?ghost=1` param
// would be forgeable, could go stale, and — worse — could be *missing* when it
// should be set, which is the direction that puts a Site Admin into a Hunt's
// Presence as a phantom body. The only thing that decides is the same fact
// §4.2 uses: are they a member of this Hunt or not.
//
// This is UX. Every write a ghost cannot make is refused by RLS, whose write
// policies were deliberately left untouched by AD-4's read predicate.
import { useAuth } from "../../auth/useAuth";
import { useMembers } from "../collaboration/api";
import { useAdminIdentity } from "./api";

export interface GhostMode {
  /** `undefined` until membership is known — never assume "member". */
  isGhost: boolean | undefined;
  /** True once the answer is settled either way. */
  resolved: boolean;
}

export function useGhostMode(huntId: string | undefined): GhostMode {
  const { session } = useAuth();
  const admin = useAdminIdentity();
  const members = useMembers(huntId ?? "");

  if (!huntId || admin.isPending || members.isPending) {
    return { isGhost: undefined, resolved: false };
  }

  // Not an admin: ordinary member, ordinary rules, nothing to decide.
  if (!admin.data?.is_site_admin) {
    return { isGhost: false, resolved: true };
  }

  const userId = session?.user.id;
  const isMember = (members.data ?? []).some((member) => member.user_id === userId);

  // An admin who genuinely belongs to this Hunt is an ordinary member here —
  // §4.2's column does not apply to them at all.
  return { isGhost: !isMember, resolved: true };
}

/** Route an ordinary Hunt mutation through the audited Ghost View surface. */
export function useGhostMutationPath(huntId: string): (path: string) => string {
  const { isGhost } = useGhostMode(huntId);
  return (path: string) => isGhost ? path.replace("/v1/", "/v1/admin/ghost/") : path;
}
