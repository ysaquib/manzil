// Typed API client (Phase 1 plan §1.6): every mutation + the one polled read
// (GET /v1/hunts/{id}/jobs). Attaches the caller's Supabase bearer token and
// throws ApiError carrying the ErrorResponse{detail, code} envelope.
import { demoSessionEnded, demoToken, isDemo } from "./demo";
import { supabase } from "./supabase";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function authHeader(): Promise<Record<string, string>> {
  // A demo session has no Supabase session to read — its token is minted by the
  // API for a subject with no account (DESIGN §20 v3.55).
  const demo = demoToken();
  if (demo) return { Authorization: `Bearer ${demo}` };

  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export interface ApiRequest<T = unknown> {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /**
   * What this write "returns" in demo mode.
   *
   * Required for any mutation whose `onSuccess` reads the response: the demo
   * branch below resolves without a round trip, so a handler that dereferences
   * an undefined result throws a TypeError and the visitor sees a broken
   * control rather than a read-only one (R2 M5). Supplying a synthetic row
   * built from the request keeps the cache update honest — it is exactly the
   * row the server would have written, and it vanishes on reload like every
   * other demo write.
   */
  demoResult?: () => T;
}

export async function apiFetch<T>(path: string, req: ApiRequest<T> = {}): Promise<T> {
  const method = req.method ?? "GET";

  // Demo mode: a write never leaves the tab.
  //
  // Not a security measure — the API and the database both refuse these anyway
  // (DESIGN §16). What this buys is honesty and quiet: the visitor's change
  // applies to the local cache and stays there, instead of a round trip that
  // exists only to come back 403 and put an error toast on screen. Resolving
  // rather than throwing is what lets each mutation's optimistic `onMutate`
  // stand as the demo's write.
  if (isDemo() && !SAFE_METHODS.has(method)) {
    return (req.demoResult?.() ?? undefined) as T;
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeader()),
  };
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
    signal: req.signal,
  });

  if (!response.ok) {
    // A demo session that stops authenticating has expired or been revoked —
    // every kill-switch toggle rotates the demo generation, so this is a real
    // path, not only a clock running out. Leaving the visitor on a page whose
    // reads have silently stopped is the worst option available.
    if (response.status === 401 && isDemo()) demoSessionEnded();

    let code = "unknown";
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { code?: string; detail?: string };
      code = payload.code ?? code;
      detail = payload.detail ?? detail;
    } catch {
      // non-JSON error body — keep the status text
    }
    if (isDemo() && code === "demo_unavailable") demoSessionEnded();
    throw new ApiError(response.status, code, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Authenticated binary read, used for private Demo map stills. */
export async function apiFetchBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: await authHeader(),
    signal,
  });
  if (!response.ok) {
    if (response.status === 401 && isDemo()) demoSessionEnded();
    let code = "unknown";
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { code?: string; detail?: string };
      code = payload.code ?? code;
      detail = payload.detail ?? detail;
    } catch {
      // Keep the HTTP status text for a non-JSON upstream error.
    }
    if (isDemo() && code === "demo_unavailable") demoSessionEnded();
    throw new ApiError(response.status, code, detail);
  }
  return response.blob();
}
