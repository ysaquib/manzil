// Admin panel data hooks (AD-2).
//
// Everything here goes through `apiFetch` rather than the direct-Supabase reads
// used elsewhere in the app, and that is the whole design: the tables behind
// these routes (`feedback`, `site_admins`, `admin_audit_log`) have no client
// SELECT policy at all, so a direct read returns an empty list rather than an
// error. The service-role admin router is the only reader.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../../lib/apiClient";

export interface AdminIdentity {
  user_id: string;
  is_site_admin: boolean;
  is_primordial: boolean;
  granted_at: string | null;
}

export interface AdminSummary {
  users: number;
  hunts: number;
  listings: number;
  jobs_failed: number;
  jobs_total: number;
  spend_usd_30d: number;
  tier3_credits_used: number;
  tier3_credits_allowance: number | null;
  feedback_new: number;
}

export interface HuntSummary {
  hunt_id: string;
  name: string;
  owner_id: string | null;
  owner_name: string | null;
  members: number;
  listings: number;
  jobs: number;
  // `total_cost_usd` is what the Hunt's Jobs billed (the Tasks-tab number).
  // The two channels come from the per-Stage breakdown, which keeps only the
  // latest attempt at each Stage, so `unattributed_cost_usd` carries the
  // difference (DESIGN §20 v3.80).
  llm_cost_usd: number;
  fetch_cost_usd: number;
  total_cost_usd: number;
  // Optional so a freshly deployed static bundle can render against an API that
  // has not rolled out yet — the two deploy independently.
  unattributed_cost_usd?: number;
  created_at: string;
  last_activity_at: string | null;
  archived_at: string | null;
  locked_at: string | null;
}

export type TriageState = "new" | "seen" | "actioned" | "wont_fix";

export interface FeedbackReport {
  id: string;
  category: string;
  body: string;
  route: string | null;
  hunt_id: string | null;
  hunt_name: string | null;
  app_version: string | null;
  user_agent: string | null;
  reporter_id: string;
  reporter_name: string | null;
  reporter_email: string | null;
  triage: TriageState;
  triaged_at: string | null;
  created_at: string;
}

export type FeedbackCounts = Record<TriageState, number>;

export const TRIAGE_STATES: { value: TriageState; label: string }[] = [
  { value: "new", label: "New" },
  { value: "seen", label: "Seen" },
  { value: "actioned", label: "Actioned" },
  { value: "wont_fix", label: "Won't fix" },
];

export const FEEDBACK_CATEGORY_LABELS: Record<string, string> = {
  bug: "Bug",
  feature: "Feature",
  confusing: "Confusing",
  wrong_data: "Wrong data",
  other: "Other",
};

// `/admin/me` answers `is_site_admin: false` instead of 403, so this runs for
// every signed-in user and must stay cheap and quiet. Cached for the session:
// admin status changes about once ever, and a reload picks it up.
export function useAdminIdentity() {
  return useQuery({
    queryKey: ["admin", "me"],
    queryFn: () => apiFetch<AdminIdentity>("/v1/admin/me"),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

// ── Demo Mode ───────────────────────────────────────────────────────────────

export interface DemoPublicationState {
  id: string;
  hunt_id: string;
  state: "queued" | "building" | "failed" | "superseded";
  attempts: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
}

export interface AdminDemoStatus {
  enabled: boolean;
  available: boolean;
  hunt_id: string | null;
  hunt_name: string | null;
  owned_by_caller: boolean;
  release_id: string | null;
  release_state: "ready" | null;
  published_at: string | null;
  replay_count: number;
  active_count: number;
  mapped_count: number;
  warnings: string[];
  blockers: string[];
  stale: boolean;
  freshness_error: string | null;
  updated_at: string;
  publication: DemoPublicationState | null;
}

export interface DemoHuntOption {
  hunt_id: string;
  name: string;
  active_listings: number;
  archived_listings: number;
}

export interface DemoPreflight {
  confirmation_id: string;
  source_fingerprint: string;
  expires_in: number;
  hunt_id: string;
  hunt_name: string;
  active_listings: number;
  archived_listings: number;
  replay_ready: number;
  mapped_properties: number;
  human_content: Record<string, number>;
  blockers: string[];
  warnings: string[];
}

export function useAdminDemoStatus() {
  return useQuery({
    queryKey: ["admin", "demo"],
    queryFn: () => apiFetch<AdminDemoStatus>("/v1/admin/demo"),
    refetchInterval: (query) => {
      const state = query.state.data?.publication?.state;
      return state === "queued" || state === "building" ? 2_000 : false;
    },
  });
}

export function useDemoHuntOptions(query: string) {
  const term = query.trim();
  return useQuery({
    queryKey: ["admin", "demo", "hunts", term],
    queryFn: () =>
      apiFetch<DemoHuntOption[]>(`/v1/admin/demo/hunts?q=${encodeURIComponent(term)}`),
    staleTime: 30_000,
  });
}

export function useDemoPreflight() {
  return useMutation({
    mutationFn: (huntId: string) =>
      apiFetch<DemoPreflight>("/v1/admin/demo/preflight", {
        method: "POST",
        body: { hunt_id: huntId },
      }),
  });
}

export function usePublishDemo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      confirmationId: string;
      confirmationText: string;
      enableOnSuccess: boolean;
    }) =>
      apiFetch<{ publication_id: string; state: string }>("/v1/admin/demo/publications", {
        method: "POST",
        body: {
          confirmation_id: input.confirmationId,
          confirmation_text: input.confirmationText,
          enable_on_success: input.enableOnSuccess,
        },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "demo"] }),
  });
}

export function useToggleDemo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      apiFetch<{ enabled: boolean }>("/v1/admin/demo", {
        method: "PATCH",
        body: { enabled },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "demo"] }),
  });
}

export function useAdminSummary(enabled = true) {
  return useQuery({
    queryKey: ["admin", "summary"],
    queryFn: () => apiFetch<AdminSummary>("/v1/admin/summary"),
    enabled,
  });
}

export interface HuntPage {
  items: HuntSummary[];
  total: number;
}

export interface HuntManagementMember {
  user_id: string;
  display_name: string;
  role: "owner" | "curator" | "member";
}

export interface HuntManagement {
  hunt_id: string;
  name: string;
  owner_id: string;
  owner_name: string;
  caller_is_member: boolean;
  archived_at: string | null;
  locked_at: string | null;
  members: HuntManagementMember[];
  deletion_blockers: string[];
}

export interface HuntDeleteResult {
  hunt_id: string;
  name: string;
  members: number;
  listings: number;
  jobs: number;
  visits: number;
}

/**
 * One page of the Hunt table (AD-4).
 *
 * Search, ordering and slicing are all the server's: this route carries
 * per-Hunt roll-ups, so "fetch everything and filter in the browser" costs the
 * whole installation's cost aggregation on every keystroke. `total` comes back
 * with the page because a pager cannot render "of N" without it.
 */
export function useAdminHunts(
  { search, limit, offset }: { search: string; limit: number; offset: number },
  enabled = true,
) {
  const term = search.trim();
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (term) params.set("search", term);
  return useQuery({
    queryKey: ["admin", "hunts", "list", term, limit, offset],
    queryFn: () => apiFetch<HuntPage>(`/v1/admin/hunts?${params.toString()}`),
    enabled,
    // Without this the table blanks to a spinner on every keystroke and every
    // page step; keeping the previous page visible while the next loads is what
    // makes paging feel like paging.
    placeholderData: (previous) => previous,
  });
}

export function useAdminHuntManagement(huntId: string | null) {
  return useQuery({
    queryKey: ["admin", "hunts", "management", huntId],
    queryFn: () =>
      apiFetch<HuntManagement>(`/v1/admin/hunts/${huntId}/management`),
    enabled: huntId !== null,
  });
}

export function useTransferAdminHuntOwnership(huntId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (newOwnerId: string) =>
      apiFetch<{ status: string }>(`/v1/admin/hunts/${huntId}/transfer-ownership`, {
        method: "POST",
        body: { new_owner_id: newOwnerId },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "hunts"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
      void queryClient.invalidateQueries({ queryKey: ["hunt_members", huntId] });
      void queryClient.invalidateQueries({ queryKey: ["hunt_contributors", huntId] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "demo"] });
    },
  });
}

export function useSetAdminHuntLock(huntId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (locked: boolean) =>
      apiFetch<HuntManagement>(`/v1/admin/hunts/${huntId}/lock`, {
        method: "PUT",
        body: { locked },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "hunts"] });
      void queryClient.invalidateQueries({ queryKey: ["hunts"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
  });
}

export function useDeleteAdminHunt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ huntId, confirmationName }: { huntId: string; confirmationName: string }) =>
      apiFetch<HuntDeleteResult>(`/v1/admin/hunts/${huntId}`, {
        method: "DELETE",
        body: { confirmation_name: confirmationName },
      }),
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "hunts"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "summary"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
      void queryClient.invalidateQueries({ queryKey: ["hunts"] });
      void queryClient.removeQueries({ queryKey: ["hunts", variables.huntId] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "demo"] });
    },
  });
}

export interface HuntOption {
  hunt_id: string;
  name: string;
  owner_name: string | null;
}

/** Minimum characters before the Hunt typeahead asks the server anything. */
export const HUNT_SEARCH_MIN_CHARS = 3;

/**
 * Hunt suggestions for a picker (AD-3).
 *
 * Deliberately *not* `useAdminHunts`: that route returns every Hunt in the
 * installation with per-Hunt roll-ups, which is fine for a table someone
 * navigated to and ruinous for a dropdown that opens on focus. Below the
 * threshold the query is disabled, so an unfocused picker costs one request:
 * none.
 */
export function useHuntOptions(query: string) {
  const term = query.trim();
  return useQuery({
    queryKey: ["admin", "hunts", "options", term],
    queryFn: () =>
      apiFetch<HuntOption[]>(`/v1/admin/hunts/options?q=${encodeURIComponent(term)}`),
    enabled: term.length >= HUNT_SEARCH_MIN_CHARS,
    // Typing "bro" → "broo" → "bro" should not re-hit the server.
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}

export function useAdminFeedback(triage: TriageState | null, enabled = true) {
  return useQuery({
    queryKey: ["admin", "feedback", triage],
    queryFn: () =>
      apiFetch<FeedbackReport[]>(
        `/v1/admin/feedback${triage ? `?triage=${triage}` : ""}`,
      ),
    enabled,
  });
}

export function useFeedbackCounts(enabled = true) {
  return useQuery({
    queryKey: ["admin", "feedback", "counts"],
    queryFn: () => apiFetch<FeedbackCounts>("/v1/admin/feedback/counts"),
    enabled,
  });
}

export function useSetTriage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, triage }: { id: string; triage: TriageState }) =>
      apiFetch<FeedbackReport>(`/v1/admin/feedback/${id}`, {
        method: "PATCH",
        body: { triage },
      }),
    // Both the list and the counts move together — triaging a report takes it
    // out of one filter and puts it in another, so refreshing only the list
    // would leave the chips lying.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "feedback"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "summary"] });
    },
  });
}

// ── People (AD-3) ───────────────────────────────────────────────────────────

export interface PersonMembership {
  hunt_id: string;
  hunt_name: string;
  role: "owner" | "curator" | "member";
  joined_at: string | null;
}

export interface PersonRow {
  user_id: string;
  email: string | null;
  display_name: string | null;
  confirmed: boolean;
  suspended: boolean;
  hunts: number;
  owns: number;
  created_at: string;
  last_sign_in_at: string | null;
  spend_usd: number;
  is_site_admin: boolean;
}

export interface PersonDetail extends PersonRow {
  memberships: PersonMembership[];
  feedback_count: number;
  /** Non-empty means Delete is refused; each entry is a Hunt to transfer. */
  blocking_owned_hunts: PersonMembership[];
}

export function useAdminPeople(search: string) {
  return useQuery({
    queryKey: ["admin", "people", search],
    queryFn: () =>
      apiFetch<PersonRow[]>(
        `/v1/admin/people${search ? `?search=${encodeURIComponent(search)}` : ""}`,
      ),
  });
}

export function useAdminPerson(userId: string | null) {
  return useQuery({
    queryKey: ["admin", "people", "detail", userId],
    queryFn: () => apiFetch<PersonDetail>(`/v1/admin/people/${userId}`),
    enabled: userId !== null,
  });
}

// One hook for every account action: they all invalidate exactly the same two
// queries, and splitting them would be five copies of this comment.
export function usePersonAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      action,
    }: {
      userId: string;
      action: "suspend" | "restore" | "password-reset";
    }) => apiFetch<{ status: string; detail: string | null }>(
      `/v1/admin/people/${userId}/${action}`,
      { method: "POST" },
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
    },
  });
}

export function useSetMembership() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      huntId,
      role,
    }: {
      userId: string;
      huntId: string;
      role: PersonMembership["role"];
    }) =>
      apiFetch<PersonDetail>(`/v1/admin/people/${userId}/memberships`, {
        method: "PUT",
        body: { hunt_id: huntId, role },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "hunts"] });
    },
  });
}

export function useRemoveMembership() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, huntId }: { userId: string; huntId: string }) =>
      apiFetch<PersonDetail>(`/v1/admin/people/${userId}/memberships/${huntId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "hunts"] });
      void queryClient.invalidateQueries({ queryKey: ["hunt_members"] });
      void queryClient.invalidateQueries({ queryKey: ["hunt_contributors"] });
    },
  });
}

export function useDeletePerson() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiFetch<void>(`/v1/admin/people/${userId}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "summary"] });
    },
  });
}

export function useProvisionPerson() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; hunt_id?: string; role?: string }) =>
      apiFetch<{ status: string; detail: string | null }>("/v1/admin/people", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "people"] });
    },
  });
}

// ── Hunts + activity (AD-4) ─────────────────────────────────────────────────

export interface ActivityEntry {
  hunt_id: string;
  occurred_at: string;
  actor_id: string | null;
  kind: string;
  subject_type: string;
  subject_id: string | null;
  subject_label: string | null;
  detail: Record<string, unknown>;
}

export function useHuntActivity(huntId: string | null) {
  return useQuery({
    queryKey: ["admin", "hunts", "activity", huntId],
    queryFn: () => apiFetch<ActivityEntry[]>(`/v1/admin/hunts/${huntId}/activity`),
    enabled: huntId !== null,
  });
}

// ── Jobs / Costs / System (AD-5) ────────────────────────────────────────────

export interface JobRow {
  id: string;
  hunt_id: string | null;
  hunt_name: string | null;
  listing_name: string | null;
  type: string;
  state: string;
  current_stage: string | null;
  attempts: number;
  error: string | null;
  cost_actual_usd: number;
  created_at: string;
  finished_at: string | null;
  locked_by: string | null;
  locked_at: string | null;
  stale: boolean;
}

export interface SpendBucket {
  label: string;
  llm_cost_usd: number;
  fetch_cost_usd: number;
  total_cost_usd: number;
  // Non-zero only for Hunt-scoped buckets: spend from Stages that ran more
  // than once, which the per-Stage breakdown replaced (DESIGN §20 v3.80).
  unattributed_cost_usd?: number;
  llm_calls: number;
  fetch_calls: number;
}

export interface CostsReport {
  days: number;
  total_cost_usd?: number;
  by_stage: SpendBucket[];
  by_hunt: SpendBucket[];
  by_model: SpendBucket[];
  grouped_by_current_pin: boolean;
  daily: { day: string; llm_cost_usd: number; fetch_cost_usd: number }[];
  tier3_credits_used: number;
  tier3_credits_allowance: number | null;
}

export interface SystemReport {
  queued: number;
  running: number;
  stale_locks: number;
  oldest_queued_seconds: number;
  worker_status: "live_idle" | "live_busy" | "unavailable";
  live_workers: number;
  busy_workers: number;
  last_heartbeat: string | null;
  finished_24h: number;
  failed_24h: number;
  last_migration: string | null;
  model_pins: {
    stage: string;
    model: string;
    input_per_mtok: number | null;
    output_per_mtok: number | null;
  }[];
  services: { name: string; detail: string; configured: boolean }[];
  priced_models: number;
  mode: string;
}

export interface AuditEntry {
  id: string;
  admin_user_id: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_label: string | null;
  hunt_id: string | null;
  via_ghost_view: boolean;
  occurred_at: string;
}

export function useAdminJobs(state: string | null, staleOnly: boolean) {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  if (staleOnly) params.set("stale_only", "true");
  const query = params.toString();
  return useQuery({
    queryKey: ["admin", "jobs", state, staleOnly],
    queryFn: () => apiFetch<JobRow[]>(`/v1/admin/jobs${query ? `?${query}` : ""}`),
    // The queue moves on its own; without this the operator is reading history.
    refetchInterval: 10_000,
  });
}

export function useJobAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, action }: { jobId: string; action: "retry" | "cancel" }) =>
      apiFetch<{ status: string; detail: string | null }>(
        `/v1/admin/jobs/${jobId}/${action}`,
        { method: "POST" },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "summary"] });
    },
  });
}

export function useAdminDeleteJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      apiFetch<{ status: string; detail: string | null }>(`/v1/admin/jobs/${jobId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "summary"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "costs"] });
    },
  });
}

export function useReleaseLocks() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; detail: string | null }>("/v1/admin/jobs/release-locks", {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "system"] });
    },
  });
}

export function useCosts(days: number) {
  return useQuery({
    queryKey: ["admin", "costs", days],
    queryFn: () => apiFetch<CostsReport>(`/v1/admin/costs?days=${days}`),
  });
}

export function useSystem() {
  return useQuery({
    queryKey: ["admin", "system"],
    queryFn: () => apiFetch<SystemReport>("/v1/admin/system"),
    refetchInterval: 15_000,
  });
}

export function useAuditLog() {
  return useQuery({
    queryKey: ["admin", "audit"],
    queryFn: () => apiFetch<AuditEntry[]>("/v1/admin/audit"),
  });
}
