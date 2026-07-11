import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";
import type { components } from "../../lib/generated/api";

export interface InviteAccepted {
  hunt_id: string;
}

export type Invite = components["schemas"]["InviteResponse"];
type InviteCreate = components["schemas"]["InviteCreate"];

export function useAcceptInvite(token: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<InviteAccepted>(`/v1/invites/${encodeURIComponent(token)}/accept`, {
        method: "POST",
      }),
  });
}

// Owner-only: pending invites for a hunt (each carries its copy-link URL).
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
