// Where sign-in sends you afterwards.
//
// Two rules, and they pull in opposite directions. A flow that *started*
// somewhere — an invite link, a join link — has to resume there or the email
// the person clicked was pointless. Everything else goes to the homepage:
// restoring an arbitrary stale target (a Hunt this account is not a member of,
// a page from a previous session) strands people on a blank screen and is the
// shape an open redirect takes if the value ever comes from outside.
//
// So the allow-list is deliberately tiny, and every consumer — the login page,
// the auth callback, the password reset — runs the value through it rather than
// trusting the URL it was handed.

/** Route prefixes worth resuming after authentication. */
const RESUMABLE = ["/invite/", "/join/"];

/** True when this target is one of the flows that must survive a sign-in. */
export function isResumableTarget(value: string | null | undefined): value is string {
  // Same-origin absolute paths only: `//evil.example` is a protocol-relative
  // URL, not a path, and `startsWith("/invite/")` alone would not catch it.
  if (!value || !value.startsWith("/") || value.startsWith("//")) return false;
  return RESUMABLE.some((prefix) => value.startsWith(prefix));
}

/** The post-authentication landing page: the resumable target, or home. */
export function safeReturnTo(value: string | null | undefined): string {
  return isResumableTarget(value) ? value : "/";
}

/** `?next=` for a login/callback URL — omitted entirely when it would be "/". */
export function nextQuery(value: string | null | undefined): string {
  return isResumableTarget(value) ? `?next=${encodeURIComponent(value)}` : "";
}
