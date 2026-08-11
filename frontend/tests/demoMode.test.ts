// DM-7: the client-side half of Demo Mode.
//
// None of this is a security boundary — the database refuses a demo write
// whether or not any of it works (DESIGN §16). These tests pin the *product*
// promises instead: a demo edit never leaves the tab, reads still work, and the
// session cannot outlive the tab.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TOKEN_KEY = "manzil-demo-token";
const HUNT_KEY = "manzil-demo-hunt";

/**
 * A syntactically real JWT; only the payload is ever read client-side.
 *
 * It has to carry a live `exp` now: `demoToken()` rejects and clears anything
 * that is not a well-formed, unexpired demo token, so that a stray value under
 * the storage key cannot put the app into a permanent read-only state with no
 * way out (R2 M4).
 */
function fakeToken(sub: string, exp = Math.floor(Date.now() / 1000) + 900): string {
  const b64 = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub, exp, manzil_demo: true })}.sig`;
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

  it("enters the Demo Hunt through the real Hunt route", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { assign, reload: vi.fn() },
      writable: true,
    });
    const token = fakeToken("abc");
    const { enterDemo } = await import("../src/lib/demo");

    enterDemo(token, "hunt-1");

    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe(token);
    expect(window.sessionStorage.getItem(HUNT_KEY)).toBe("hunt-1");
    expect(assign).toHaveBeenCalledWith("/h/hunt-1");
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

  it("exposes response headers alongside parsed JSON when requested", async () => {
    const headers = new Headers({ "X-Manzil-Backfill-Count": "3" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers,
        json: async () => [{ id: "criterion-1" }],
      }),
    );

    const { apiFetchResult } = await import("../src/lib/apiClient");
    const result = await apiFetchResult<{ id: string }[]>("/v1/rubric", { method: "PUT" });

    expect(result.data).toEqual([{ id: "criterion-1" }]);
    expect(result.headers.get("X-Manzil-Backfill-Count")).toBe("3");
  });
});

// ── R2 M4: a stored value is only a session if it is actually usable ─────────

describe("demo session validity", () => {
  it("ignores and clears an expired token", async () => {
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("abc", Math.floor(Date.now() / 1000) - 60));
    const { isDemo } = await import("../src/lib/demo");
    expect(isDemo()).toBe(false);
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("ignores and clears a value that is not a demo token at all", async () => {
    // The failure this prevents: any junk under the storage key used to put the
    // whole app into a permanent read-only state — every write silently
    // swallowed — with no way out but finding the Exit control.
    window.sessionStorage.setItem(TOKEN_KEY, "not-a-jwt");
    const { isDemo } = await import("../src/lib/demo");
    expect(isDemo()).toBe(false);
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("ignores a well-formed JWT that is not ours", async () => {
    const b64 = (value: object) =>
      btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const notDemo = `${b64({ alg: "HS256" })}.${b64({
      sub: "abc",
      exp: Math.floor(Date.now() / 1000) + 900,
    })}.sig`;
    window.sessionStorage.setItem(TOKEN_KEY, notDemo);
    const { isDemo } = await import("../src/lib/demo");
    expect(isDemo()).toBe(false);
  });
});

// ── R2 M5: an intercepted write must not break its own success handler ───────

describe("intercepted writes return something usable", () => {
  beforeEach(() => {
    window.sessionStorage.setItem(TOKEN_KEY, fakeToken("11111111-2222-3333-4444-555555555555"));
  });

  it("resolves a declared synthetic result instead of undefined", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { apiFetch } = await import("../src/lib/apiClient");

    const result = await apiFetch<{ id: string }>("/v1/visits/v1", {
      method: "PATCH",
      body: {},
      demoResult: () => ({ id: "v1" }),
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result).toEqual({ id: "v1" });
  });

  it("still resolves undefined when no result is declared", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const { apiFetch } = await import("../src/lib/apiClient");
    await expect(apiFetch("/v1/anything", { method: "POST" })).resolves.toBeUndefined();
  });

  it("every mutation whose result is used declares one, or is named as guarded", () => {
    // A structural check rather than a per-hook test: the failure mode is a
    // TypeError thrown from a click handler, which only shows up when a visitor
    // clicks the control.
    //
    // The first version of this test was near-vacuous in three separate ways
    // (`F8`), and all three are fixed here:
    //
    //  * its glob was `**/*.ts`, which **does not match `.tsx`** — so every
    //    component, i.e. every place a mutation is actually called, was invisible
    //    to it;
    //  * it looked only for `onSuccess`, missing `await mutateAsync(...)`,
    //    `.then()` and `mutation.data`;
    //  * and it asserted that the *file* contained the string `demoResult`, so
    //    one hook declaring one absolved every other hook in the module.
    //
    // What it checks now: a mutation hook whose result is dereferenced anywhere
    // must either declare `demoResult` on its own `apiFetch` call, or be named
    // in a `demo-guarded:` comment at the site that dereferences it. Only hooks
    // whose write goes through `apiFetch` with an unsafe method are in scope —
    // a hook writing through `supabase.from(...)` is refused by the database and
    // lands in `onError`, so its success handler never runs at all.
    const modules = import.meta.glob("../src/features/**/*.{ts,tsx}", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;

    // ── Pass 1: the mutation hooks, and whether each declares a demo result ──
    interface Hook {
      path: string;
      body: string;
      declaresDemoResult: boolean;
    }
    const hooks = new Map<string, Hook>();
    for (const [path, source] of Object.entries(modules)) {
      const starts = [...source.matchAll(/export function (use[A-Z]\w*)\s*\(/g)];
      starts.forEach((start, i) => {
        const from = start.index!;
        const to = i + 1 < starts.length ? starts[i + 1].index! : source.length;
        const body = source.slice(from, to);
        if (!body.includes("useMutation(")) return;
        if (!body.includes("apiFetch")) return;
        if (!/method:\s*"(POST|PUT|PATCH|DELETE)"/.test(body)) return;
        hooks.set(start[1], { path, body, declaresDemoResult: body.includes("demoResult") });
      });
    }

    // ── Pass 2: every place a mutation's result is dereferenced ─────────────
    // A destructured parameter counts: `({ hunt_id }) =>` is a dereference that
    // throws on `undefined` exactly as `x.hunt_id` does.
    const PARAM = String.raw`\(\s*(\{[^)]*\}|[A-Za-z_$][\w$]*)\s*[,)]`;
    const uses: { hook: string; site: string; why: string }[] = [];
    const note = (hook: string, site: string, why: string) => {
      if (hooks.has(hook)) uses.push({ hook, site, why });
    };

    for (const [path, source] of Object.entries(modules)) {
      // (a) A hook that names the response in its own onSuccess.
      for (const [name, hook] of hooks) {
        if (hook.path !== path) continue;
        for (const match of hook.body.matchAll(
          new RegExp(String.raw`onSuccess:\s*(?:async\s*)?` + PARAM, "g"),
        )) {
          if (/^_/.test(match[1])) continue; // conventionally unused
          note(name, path, `its own onSuccess names the response as \`${match[1]}\``);
        }
      }

      // (b) Call sites. Bind local names to the hooks they come from, then look
      //     for the four shapes a result gets used in.
      const bindings = new Map<string, string>();
      for (const match of source.matchAll(
        /(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(use[A-Z]\w*)\s*\(/g,
      )) {
        if (hooks.has(match[2])) bindings.set(match[1], match[2]);
      }
      if (bindings.size === 0) continue;

      for (const [local, hook] of bindings) {
        // `const visit = await createVisit.mutateAsync(...)` — binding the
        // response to a name is the point of `mutateAsync` over `mutate`.
        if (new RegExp(String.raw`=\s*await\s+${local}\.mutateAsync\s*\(`).test(source)) {
          note(hook, path, `\`await ${local}.mutateAsync(...)\` is bound to a name`);
        }
        // `accept.data.hunt_id` — the mutation-object form, which also never
        // becomes truthy in demo mode and so hangs the page rather than throwing.
        if (new RegExp(String.raw`\b${local}\.data\b`).test(source)) {
          note(hook, path, `\`${local}.data\` is read`);
        }
      }

      // Inline handlers passed at the call site. Chunking the file at each
      // `.mutate(`/`.mutateAsync(` keeps a handler attributed to the mutation it
      // was actually passed to, rather than to whichever one a lazy regex
      // reached first.
      const calls = [...source.matchAll(/([A-Za-z_$][\w$]*)\.mutate(?:Async)?\s*\(/g)];
      calls.forEach((call, i) => {
        const hook = bindings.get(call[1]);
        if (!hook) return;
        const chunk = source.slice(
          call.index!,
          i + 1 < calls.length ? calls[i + 1].index! : source.length,
        );
        const handler = chunk.match(
          new RegExp(String.raw`(?:onSuccess:|\.then\()\s*(?:async\s*)?` + PARAM),
        );
        if (handler && !/^_/.test(handler[1])) {
          note(hook, path, `a handler at the call site names the response as \`${handler[1]}\``);
        }
      });
    }

    // Guards the guard. If the glob, the hook scan or the use scan silently
    // matched nothing, everything below would pass while checking nothing — the
    // exact way the previous version of this test went green over `F5`–`F7`.
    expect(hooks.size, "no intercepted mutation hooks were found").toBeGreaterThan(20);
    expect(
      [...hooks.values()].filter((h) => h.declaresDemoResult).length,
      "no hook declares a demo result",
    ).toBeGreaterThan(3);
    expect(new Set(uses.map((u) => u.why.slice(0, 12))).size).toBeGreaterThan(2);
    expect(
      Object.keys(modules).filter((p) => p.endsWith(".tsx")).length,
      "the glob is not reaching components",
    ).toBeGreaterThan(20);

    // ── The assertion ───────────────────────────────────────────────────────
    // Opting out is allowed and must be deliberate: the dereferencing site
    // carries a comment naming the hook, next to the reason the demo never
    // reaches it. The marker names the *hook*, not the file, because a
    // file-level signal is what made the previous version of this test vacuous
    // — one hook's `demoResult` absolved every other in the module.
    //
    // What the marker cannot prove is that the guard beside it works; a reader
    // has to check that, and the comment exists to make them. It is not a
    // weaker rule than the one it replaces, because there was no rule.
    const offenders = uses
      .filter(
        ({ hook, site }) =>
          !hooks.get(hook)!.declaresDemoResult && !modules[site].includes(`demo-guarded: ${hook}`),
      )
      .map(({ hook, site, why }) => `${hook} (${site}): ${why}`);

    expect(
      offenders,
      "these mutations use a response that demo mode never produces; give the " +
        "hook a `demoResult`, or guard the site and add a `demo-guarded: <hook>` note",
    ).toEqual([]);
  });
});
