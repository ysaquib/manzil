// Demo Mode, client side (DM-7, DESIGN §16, §20 v3.53–v3.55).
//
// This module is deliberately not a React hook. `apiClient`, `queryClient`,
// `realtime` and `supabase` all need to know whether this is a demo session, and
// three of them run before React mounts — `supabase` builds its client at module
// load, and the query client is configured at import time.
//
// **None of this is a security control.** A demo token is read-only because the
// database refuses its writes (DESIGN §16); everything here exists so the app
// feels honest and costs nothing, not so it is safe. Anyone can edit these
// values in devtools and the guarantees do not change.
//
// The token lives in sessionStorage rather than localStorage on purpose: a demo
// is a visit, not an account. Closing the tab ends it, and "reload resets
// everything" — the demo's core promise — stays true of the session too.

const TOKEN_KEY = "manzil-demo-token";
const HUNT_KEY = "manzil-demo-hunt";

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // Safari in private mode, or storage disabled entirely. Demo mode simply
    // is not offered; the rest of the app is unaffected.
    return null;
  }
}

/** The demo access token for this tab, or null. */
export function demoToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null;
}

/** The Demo Hunt id, so the app can route straight into it. */
export function demoHuntId(): string | null {
  return storage()?.getItem(HUNT_KEY) ?? null;
}

/**
 * Whether this tab is a demo session.
 *
 * Read at module scope by `supabase.ts` and `queryClient.ts`, so it must stay
 * synchronous and must not depend on anything React has mounted.
 */
export function isDemo(): boolean {
  return demoToken() !== null;
}

/**
 * The demo principal's id, read from the token's `sub`.
 *
 * Decoded without verification, which is fine because it is used only to
 * attribute optimistic rows in the local cache. Nothing is authorised from it —
 * the server re-derives the subject from the signature.
 */
export function demoPrincipalId(): string | null {
  const token = demoToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return (JSON.parse(json) as { sub?: string }).sub ?? null;
  } catch {
    return null;
  }
}

/**
 * Begin a demo session.
 *
 * Reloads deliberately. The Supabase client fixes its Authorization header when
 * it is constructed, and the query client fixes its options at import — so
 * entering demo mode part-way through a page would leave both configured for an
 * ordinary user. A reload is also exactly what leaving demo mode does, which
 * keeps the two directions symmetric and the state impossible to half-apply.
 */
export function enterDemo(token: string, huntId: string | null): void {
  const store = storage();
  if (!store) return;
  store.setItem(TOKEN_KEY, token);
  if (huntId) store.setItem(HUNT_KEY, huntId);
  window.location.assign(huntId ? `/hunts/${huntId}` : "/");
}

/** End the demo session and return to a clean, signed-out app. */
export function exitDemo(): void {
  const store = storage();
  store?.removeItem(TOKEN_KEY);
  store?.removeItem(HUNT_KEY);
  window.location.assign("/login");
}

/**
 * Discard everything the visitor has changed and start the demo over.
 *
 * There is nothing to undo server-side — no demo write ever reached the
 * database — so a reload is the whole implementation. That is the payoff of
 * keeping demo state in the query cache and nowhere else.
 */
export function resetDemo(): void {
  window.location.reload();
}
