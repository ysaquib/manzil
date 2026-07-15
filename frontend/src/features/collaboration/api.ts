import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../auth/useAuth";
import { apiFetch } from "../../lib/apiClient";
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
}

export interface Comment {
  id: string;
  hunt_listing_id: string;
  user_id: string;
  body: string;
  created_at: string;
  deleted_at: string | null;
}

export interface Rating {
  hunt_listing_id: string;
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
      const rows = (data ?? []) as Omit<HuntMember, "display_name_override">[];
      const userIds = rows.map((row) => row.user_id);
      const profiles = userIds.length
        ? await supabase.from("user_profiles").select("user_id, default_display_name").in("user_id", userIds)
        : { data: [], error: null };
      if (profiles.error) throw profiles.error;
      const defaults = new Map(
        (profiles.data ?? []).map((profile) => [profile.user_id, profile.default_display_name]),
      );
      return rows.map((row) => ({
        ...row,
        display_name_override: row.display_name,
        display_name: row.display_name ?? defaults.get(row.user_id) ?? null,
      }));
    },
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
    mutationFn: (body: string) =>
      apiFetch<Comment>(`/v1/listings/${listingId}/comments`, {
        method: "POST",
        body: { body },
      }),
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

export function useSetRating(listingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (rating: number | null) => {
      if (rating === null) {
        await apiFetch<void>(`/v1/listings/${listingId}/rating`, { method: "DELETE" });
      } else {
        await apiFetch<Rating>(`/v1/listings/${listingId}/rating`, {
          method: "PUT",
          body: { rating },
        });
      }
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
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] }),
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
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] }),
  });
}

// Owner-only: change another member's role (member|curator; never owner).
export function useSetMemberRole(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: "member" | "curator" }) =>
      apiFetch<MemberResponse>(`/v1/hunts/${huntId}/members/${userId}`, {
        method: "PATCH",
        body: { role } satisfies MemberPatch,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] }),
  });
}

// Owner-only: remove another member (the owner row is refused server-side).
export function useRemoveMember(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiFetch<void>(`/v1/hunts/${huntId}/members/${userId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] }),
  });
}

// Owner-only: hand ownership to an existing member; the old owner becomes Curator.
export function useTransferOwnership(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (newOwnerId: string) =>
      apiFetch<TransferOwnershipResponse>(`/v1/hunts/${huntId}/transfer-ownership`, {
        method: "POST",
        body: { new_owner_id: newOwnerId } satisfies TransferOwnershipRequest,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hunt_members", huntId] });
      void qc.invalidateQueries({ queryKey: ["hunts"] });
      void qc.invalidateQueries({ queryKey: ["hunts", huntId] });
    },
  });
}
