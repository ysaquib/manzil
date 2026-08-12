import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../auth/useAuth";
import { apiFetch } from "../../lib/apiClient";
import { demoPrincipalId } from "../../lib/demo";
import type { components } from "../../lib/generated/api";
import { supabase } from "../../lib/supabase";

type MemberPatch = components["schemas"]["MemberPatch"];
type MemberResponse = components["schemas"]["MemberResponse"];
type TransferOwnershipRequest = components["schemas"]["TransferOwnershipRequest"];
type TransferOwnershipResponse = components["schemas"]["TransferOwnershipResponse"];

export interface HuntMember {
  hunt_id: string;
  user_id: string;
  role: "owner" | "curator" | "member";
  color: string | null;
  display_name: string | null;
  display_name_override?: string | null;
  color_override?: string | null;
}

/**
 * Hunt-visible attribution for retained collaboration records.
 *
 * This is deliberately not a HuntMember: a former contributor has no
 * membership row, no access, no Presence, and no place in the current roster.
 */
export interface HuntContributor {
  user_id: string;
  display_name: string | null;
  color: string | null;
  is_former: boolean;
}

export interface Comment {
  id: string;
  hunt_listing_id: string;
  user_id: string;
  body: string;
  unit_group_key: string | null;
  created_at: string;
  edited_at: string | null;
  deleted_at: string | null;
}

export interface Rating {
  hunt_listing_id: string;
  unit_group_key: string;
  user_id: string;
  rating: number;
}

export function useMembers(huntId: string) {
  return useQuery({
    queryKey: ["hunt_members", huntId],
    queryFn: async (): Promise<HuntMember[]> => {
      const { data, error } = await supabase
        .from("hunt_members")
        .select("*")
        .eq("hunt_id", huntId);
      if (error) throw error;
      const rows = (data ?? []) as Omit<HuntMember, "display_name_override" | "color_override">[];
      // A direct `user_profiles` read is deliberately membership-scoped. That
      // is correct for ordinary members, but a Site Admin in Ghost View is not
      // a member and therefore received no defaults, reducing every current
      // person to "Member". This RPC is the narrow, Hunt-scoped attribution
      // projection: it returns effective names and colours for this Hunt only
      // and explicitly admits Site Admins (DESIGN §3 Ghost View / Former User).
      const identities = await supabase.rpc("get_hunt_contributor_identities", {
        p_hunt_id: huntId,
      });
      if (identities.error) throw identities.error;
      const byUserId = new Map(
        ((identities.data ?? []) as HuntContributor[]).map((identity) => [
          identity.user_id,
          identity,
        ]),
      );
      // Hunt-level values are overrides; null inherits the account default
      // (name always, colour when the profile has one — same rule as the DB
      // membership-insert trigger). `identities` is authoritative for the
      // inherited value and avoids widening account-profile RLS for Ghosts.
      return rows.map((row) => ({
        ...row,
        display_name_override: row.display_name,
        color_override: row.color,
        display_name: row.display_name ?? byUserId.get(row.user_id)?.display_name ?? null,
        color: row.color ?? byUserId.get(row.user_id)?.color ?? null,
      }));
    },
    refetchOnWindowFocus: true,
  });
}

export function useHuntContributors(huntId: string) {
  return useQuery({
    queryKey: ["hunt_contributors", huntId],
    queryFn: async (): Promise<HuntContributor[]> => {
      const { data, error } = await supabase.rpc("get_hunt_contributor_identities", {
        p_hunt_id: huntId,
      });
      if (error) throw error;
      return (data ?? []) as HuntContributor[];
    },
    enabled: Boolean(huntId),
    refetchOnWindowFocus: true,
  });
}

/** Signed-in user's HuntMember for this hunt; derives from useMembers (same cache). */
export function useCurrentMember(huntId: string) {
  const { session } = useAuth();
  const membersQuery = useMembers(huntId);
  const userId = session?.user.id;
  return {
    ...membersQuery,
    data: userId
      ? membersQuery.data?.find((member) => member.user_id === userId)
      : undefined,
  };
}

export function useComments(listingId: string) {
  return useQuery({
    queryKey: ["comments", listingId],
    queryFn: async (): Promise<Comment[]> => {
      const { data, error } = await supabase
        .from("comments")
        .select("*")
        .eq("hunt_listing_id", listingId)
        .is("deleted_at", null)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as Comment[];
    },
    enabled: Boolean(listingId),
    refetchOnWindowFocus: true,
  });
}

export function useRatings(listingId: string) {
  return useQuery({
    queryKey: ["ratings", listingId],
    queryFn: async (): Promise<Rating[]> => {
      const { data, error } = await supabase
        .from("ratings")
        .select("*")
        .eq("hunt_listing_id", listingId);
      if (error) throw error;
      return (data ?? []) as Rating[];
    },
    enabled: Boolean(listingId),
    refetchOnWindowFocus: true,
  });
}

export function useCreateComment(listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { body: string; unit_group_key: string | null }) =>
      apiFetch<Comment>(`/v1/listings/${listingId}/comments`, {
        method: "POST",
        body,
      }),
    // Applied before the request, and in demo mode it *is* the write: the
    // request never leaves the tab and invalidation is disabled, so this cache
    // entry is the whole result. For a real user it is an ordinary optimistic
    // update that the refetch below replaces.
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: ["comments", listingId] });
      const previous = qc.getQueryData<Comment[]>(["comments", listingId]);
      const author = demoPrincipalId();
      if (author) {
        qc.setQueryData<Comment[]>(["comments", listingId], (current = []) => [
          ...current,
          {
            id: `optimistic:${crypto.randomUUID()}`,
            hunt_listing_id: listingId,
            user_id: author,
            body: body.body,
            unit_group_key: body.unit_group_key,
            created_at: new Date().toISOString(),
          } as Comment,
        ]);
      }
      return { previous };
    },
    onError: (_error, _body, context) => {
      if (context?.previous) qc.setQueryData(["comments", listingId], context.previous);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["comments", listingId] }),
  });
}

export function useUpdateComment(listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ commentId, body }: { commentId: string; body: string }) =>
      apiFetch<Comment>(`/v1/comments/${commentId}`, { method: "PATCH", body: { body } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["comments", listingId] }),
  });
}

export function useDeleteComment(listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (commentId: string) =>
      apiFetch<void>(`/v1/comments/${commentId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["comments", listingId] }),
  });
}

export function useSetRating(listingId: string, unitGroupKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (rating: number | null) => {
      if (rating === null) {
        await apiFetch<void>(
          `/v1/listings/${listingId}/unit-groups/${encodeURIComponent(unitGroupKey)}/rating`,
          { method: "DELETE" },
        );
      } else {
        await apiFetch<Rating>(
          `/v1/listings/${listingId}/unit-groups/${encodeURIComponent(unitGroupKey)}/rating`,
          { method: "PUT", body: { rating } },
        );
      }
    },
    onMutate: async (rating) => {
      await qc.cancelQueries({ queryKey: ["ratings", listingId] });
      const previous = qc.getQueryData<Rating[]>(["ratings", listingId]);
      const author = demoPrincipalId();
      if (author) {
        qc.setQueryData<Rating[]>(["ratings", listingId], (current = []) => {
          const rest = current.filter(
            (r) => !(r.user_id === author && r.unit_group_key === unitGroupKey),
          );
          return rating === null
            ? rest
            : [
                ...rest,
                {
                  hunt_listing_id: listingId,
                  user_id: author,
                  unit_group_key: unitGroupKey,
                  rating,
                } as Rating,
              ];
        });
      }
      return { previous };
    },
    onError: (_error, _rating, context) => {
      if (context?.previous) qc.setQueryData(["ratings", listingId], context.previous);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ratings", listingId] }),
  });
}

export function useSetMemberColor(huntId: string, userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (color: string) =>
      apiFetch<MemberResponse>(`/v1/hunts/${huntId}/members/${userId}`, {
        method: "PATCH",
        body: { color } satisfies MemberPatch,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunt_contributors", huntId] });
    },
  });
}

// Self-service: PATCH own row's display_name (trimmed 1..80 server-side).
export function useSetMemberDisplayName(huntId: string, userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (display_name: string | null) =>
      apiFetch<MemberResponse>(`/v1/hunts/${huntId}/members/${userId}`, {
        method: "PATCH",
        body: { display_name } satisfies MemberPatch,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunt_contributors", huntId] });
    },
  });
}

// Owner-only: change another member's role (member|curator; never owner).
export function useSetMemberRole(huntId: string, isGhost = false) {
  const qc = useQueryClient();
  const mutationPath = (path: string) => isGhost ? path.replace("/v1/", "/v1/admin/ghost/") : path;
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: "member" | "curator" }) =>
      apiFetch<MemberResponse>(mutationPath(`/v1/hunts/${huntId}/members/${userId}`), {
        method: "PATCH",
        body: { role } satisfies MemberPatch,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] }),
  });
}

// Owner-only: remove another member (the owner row is refused server-side).
export function useRemoveMember(huntId: string, isGhost = false) {
  const qc = useQueryClient();
  const mutationPath = (path: string) => isGhost ? path.replace("/v1/", "/v1/admin/ghost/") : path;
  return useMutation({
    mutationFn: (userId: string) =>
      apiFetch<void>(mutationPath(`/v1/hunts/${huntId}/members/${userId}`), { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunt_contributors", huntId] });
    },
  });
}

// Self-service: end your own membership. The server refuses the Owner (transfer
// ownership first) and a hunt's last member (archive it instead), so the caller
// only has to surface the error. Never ghosted — a Site Admin in Ghost View has
// no membership to leave.
export function useLeaveHunt(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>(`/v1/hunts/${huntId}/leave`, { method: "POST" }),
    onSuccess: () => {
      // The hunt drops out of the switcher and its rows stop being readable, so
      // drop the caches outright rather than refetching what RLS now hides.
      qc.removeQueries({ queryKey: ["hunt_members", huntId] });
      qc.removeQueries({ queryKey: ["hunts", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunts"] });
    },
  });
}

// Owner-only: hand ownership to an existing member; the old owner becomes Curator.
export function useTransferOwnership(huntId: string, isGhost = false) {
  const qc = useQueryClient();
  const mutationPath = (path: string) => isGhost ? path.replace("/v1/", "/v1/admin/ghost/") : path;
  return useMutation({
    mutationFn: (newOwnerId: string) =>
      apiFetch<TransferOwnershipResponse>(mutationPath(`/v1/hunts/${huntId}/transfer-ownership`), {
        method: "POST",
        body: { new_owner_id: newOwnerId } satisfies TransferOwnershipRequest,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunt_contributors", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunts"] });
      void qc.invalidateQueries({ queryKey: ["hunts", huntId] });
    },
  });
}
