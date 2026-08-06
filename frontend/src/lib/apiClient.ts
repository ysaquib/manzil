// Typed API client (Phase 1 plan §1.6): every mutation + the one polled read
// (GET /v1/hunts/{id}/jobs). Attaches the caller's Supabase bearer token and
// throws ApiError carrying the ErrorResponse{detail, code} envelope.
import { demoToken, isDemo } from "./demo";
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

export interface ApiRequest {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, req: ApiRequest = {}): Promise<T> {
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
    return undefined as T;
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
    let code = "unknown";
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { code?: string; detail?: string };
      code = payload.code ?? code;
      detail = payload.detail ?? detail;
    } catch {
      // non-JSON error body — keep the status text
    }
    throw new ApiError(response.status, code, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
