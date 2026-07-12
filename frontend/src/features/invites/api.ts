import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";

export interface InviteAccepted {
  hunt_id: string;
}

export type Invite = components["schemas"]["InviteResponse"];
type InviteCreate = components["schemas"]["InviteCreate"];

export type InvitationLink = components["schemas"]["InvitationLinkResponse"];
export type InvitationLinkCreate = components["schemas"]["InvitationLinkCreate"];
export type InvitationLinkPatch = components["schemas"]["InvitationLinkPatch"];

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
  return useQuery({
    queryKey: ["invites", huntId],
    queryFn: () => apiFetch<Invite[]>(`/v1/hunts/${huntId}/invites`),
    enabled: Boolean(huntId),
  });
}

// Owner-only: mint an invite; response includes the shareable `link`.
export function useCreateInvite(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InviteCreate) =>
      apiFetch<Invite>(`/v1/hunts/${huntId}/invites`, { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites", huntId] }),
  });
}

// Owner-only: revoke a pending invite.
export function useRevokeInvite(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (inviteId: string) =>
      apiFetch<void>(`/v1/invites/${inviteId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invites", huntId] }),
  });
}

export function useInvitationLinks(huntId: string) {
  return useQuery({
    queryKey: ["invitation-links", huntId],
    queryFn: () =>
      apiFetch<InvitationLink[]>(`/v1/hunts/${huntId}/invitation-links`),
    enabled: Boolean(huntId),
  });
}

export function useCreateInvitationLink(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InvitationLinkCreate) =>
      apiFetch<InvitationLink>(`/v1/hunts/${huntId}/invitation-links`, {
        method: "POST",
        body,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitation-links", huntId] }),
  });
}

export function usePatchInvitationLink(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: InvitationLinkPatch }) =>
      apiFetch<InvitationLink>(`/v1/invitation-links/${id}`, { method: "PATCH", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitation-links", huntId] }),
  });
}

export function useDeleteInvitationLink(huntId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/v1/invitation-links/${id}`, { method: "DELETE" }),
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
