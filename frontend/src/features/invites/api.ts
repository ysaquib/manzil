import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";
import { useGhostMutationPath } from "../admin/useGhostMode";

export interface InviteAccepted {
  hunt_id: string;
}

export type Invite = components["schemas"]["InviteResponse"];
type InviteCreate = components["schemas"]["InviteCreate"];

export type InvitationLink = components["schemas"]["InvitationLinkResponse"];
export type InvitationLinkCreate = components["schemas"]["InvitationLinkCreate"];
export type InvitationLinkPatch = components["schemas"]["InvitationLinkPatch"];

export function invitationDeliveryPollInterval(invites: Invite[] | undefined): number | false {
  return invites?.some((invite) =>
    ["queued", "sending", "sent", "delayed"].includes(invite.delivery_status),
  )
    ? 5_000
    : false;
}

/** Keep copied links on the exact frontend origin that owns the active Auth session.
 * The API's configured frontend URL may legitimately differ by hostname (for
 * example www vs apex, or localhost vs a LAN host), and Supabase session
 * storage is origin-scoped.
 */
export function invitationLinkForCurrentOrigin(link: string, origin = window.location.origin) {
  const url = new URL(link);
  return `${origin}${url.pathname}${url.search}${url.hash}`;
}

export function useAcceptInvite(token: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<InviteAccepted>(`/v1/invites/${encodeURIComponent(token)}/accept`, {
        method: "POST",
      }),
  });
}

// Owner-only: pending single-recipient email invites for a hunt.
export function useInvites(huntId: string) {
  const mutationPath = useGhostMutationPath(huntId);
  return useQuery({
    queryKey: ["invites", huntId],
    queryFn: () => apiFetch<Invite[]>(mutationPath(`/v1/hunts/${huntId}/invites`)),
    enabled: Boolean(huntId),
    // Delivery state is private server data, so it cannot ride Supabase
    // Realtime. Poll only while a visible Invite can still change state.
    refetchInterval: (query) => invitationDeliveryPollInterval(query.state.data),
  });
}

// Owner-only: mint an invite; response includes the shareable `link`.
export function useCreateInvite(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (body: InviteCreate) =>
      apiFetch<Invite>(mutationPath(`/v1/hunts/${huntId}/invites`), { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites", huntId] }),
  });
}

export function useResendInvite(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (inviteId: string) =>
      apiFetch<Invite>(mutationPath(`/v1/invites/${inviteId}/resend`), { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites", huntId] }),
  });
}

// Owner-only: revoke a pending invite.
export function useRevokeInvite(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (inviteId: string) =>
      apiFetch<void>(mutationPath(`/v1/invites/${inviteId}`), { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites", huntId] }),
  });
}

export function useInvitationLinks(huntId: string) {
  const mutationPath = useGhostMutationPath(huntId);
  return useQuery({
    queryKey: ["invitation-links", huntId],
    queryFn: () =>
      apiFetch<InvitationLink[]>(mutationPath(`/v1/hunts/${huntId}/invitation-links`)),
    enabled: Boolean(huntId),
  });
}

export function useCreateInvitationLink(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (body: InvitationLinkCreate) =>
      apiFetch<InvitationLink>(mutationPath(`/v1/hunts/${huntId}/invitation-links`), {
        method: "POST",
        body,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitation-links", huntId] }),
  });
}

export function usePatchInvitationLink(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: InvitationLinkPatch }) =>
      apiFetch<InvitationLink>(mutationPath(`/v1/invitation-links/${id}`), { method: "PATCH", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitation-links", huntId] }),
  });
}

export function useDeleteInvitationLink(huntId: string) {
  const qc = useQueryClient();
  const mutationPath = useGhostMutationPath(huntId);
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(mutationPath(`/v1/invitation-links/${id}`), { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitation-links", huntId] }),
  });
}

export function useJoinInvitationLink(token: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<InviteAccepted>(`/v1/invitation-links/${encodeURIComponent(token)}/join`, {
        method: "POST",
      }),
  });
}
