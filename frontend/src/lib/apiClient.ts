// Typed API client (Phase 1 plan §1.6): every mutation + the one polled read
// (GET /v1/hunts/{id}/jobs). Attaches the caller's Supabase bearer token and
// throws ApiError carrying the ErrorResponse{detail, code} envelope.
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
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface ApiRequest {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, req: ApiRequest = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeader()),
  };
  const response = await fetch(`${BASE_URL}${path}`, {
    method: req.method ?? "GET",
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
