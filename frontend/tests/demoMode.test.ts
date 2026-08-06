// DM-7: the client-side half of Demo Mode.
//
// None of this is a security boundary — the database refuses a demo write
// whether or not any of it works (DESIGN §16). These tests pin the *product*
// promises instead: a demo edit never leaves the tab, reads still work, and the
// session cannot outlive the tab.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TOKEN_KEY = "manzil-demo-token";
const HUNT_KEY = "manzil-demo-hunt";

/** A syntactically real JWT; only the payload is ever read client-side. */
function fakeToken(sub: string): string {
  const b64 = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub, manzil_demo: true })}.sig`;
}

beforeEach(() => {
  vi.resetModules();
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("demo session state", () => {
  it("is off unless a token is present", async () => {
    const { isDemo, demoPrincipalId } = await import("../src/lib/demo");
    expect(isDemo()).toBe(false);
    expect(demoPrincipalId()).toBeNull();
  });

  it("reads the principal from the token's sub", async () => {
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("11111111-2222-3333-4444-555555555555"));
    const { isDemo, demoPrincipalId } = await import("../src/lib/demo");
    expect(isDemo()).toBe(true);
    expect(demoPrincipalId()).toBe("11111111-2222-3333-4444-555555555555");
  });

  it("survives a malformed token without throwing", async () => {
    // A truncated or tampered token must degrade to "no principal", not crash
    // the app on load — this runs at module scope in supabase.ts.
    window.sessionStorage.setItem(TOKEN_KEY, "not-a-jwt");
    const { demoPrincipalId } = await import("../src/lib/demo");
    expect(demoPrincipalId()).toBeNull();
  });

  it("keeps the session in sessionStorage, so it cannot outlive the tab", async () => {
    const { demoToken } = await import("../src/lib/demo");
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("abc"));
    window.localStorage.setItem(TOKEN_KEY, "should-be-ignored");
    expect(demoToken()).toBe(window.sessionStorage.getItem(TOKEN_KEY));
  });

  it("clears both keys when leaving", async () => {
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("abc"));
    window.sessionStorage.setItem(HUNT_KEY, "hunt-1");
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { assign, reload: vi.fn() },
      writable: true,
    });
    const { exitDemo } = await import("../src/lib/demo");
    exitDemo();
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(HUNT_KEY)).toBeNull();
    expect(assign).toHaveBeenCalledWith("/login");
  });
});

describe("apiFetch in demo mode", () => {
  it("never sends an unsafe request", async () => {
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("abc"));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const { apiFetch } = await import("../src/lib/apiClient");
    for (const method of ["POST", "PUT", "PATCH", "DELETE"] as const) {
      await apiFetch("/v1/anything", { method, body: { a: 1 } });
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("resolves rather than throwing, so optimistic updates stand", async () => {
    // If the interception threw, every mutation's onError would roll the
    // visitor's change straight back and the demo would look broken.
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("abc"));
    vi.stubGlobal("fetch", vi.fn());
    const { apiFetch } = await import("../src/lib/apiClient");
    await expect(apiFetch("/v1/anything", { method: "POST" })).resolves.toBeUndefined();
  });

  it("still performs reads, and carries the demo token", async () => {
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("abc"));
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { apiFetch } = await import("../src/lib/apiClient");
    await apiFetch("/v1/hunts");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers.Authorization).toBe(
      `Bearer ${window.sessionStorage.getItem(TOKEN_KEY)}`,
    );
  });

  it("leaves a normal session's writes alone", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const { apiFetch } = await import("../src/lib/apiClient");
    await apiFetch("/v1/anything", { method: "POST", body: { a: 1 } });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
