// supabase-js client (Phase 1 plan §1.6): auth session + direct RLS-guarded
// reads of continuously-rendered table data. Mutations go through apiClient.ts.
import { createClient } from "@supabase/supabase-js";

import { demoToken } from "./demo";

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  // Fail loud in dev — a missing anon key silently breaks every read.
  console.warn("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY not set — see .env.example");
}

// A demo session carries a server-minted token instead of a Supabase session
// (DESIGN §20 v3.55). Its subject has no `auth.users` row, so there is nothing
// for GoTrue to sign in, refresh, or sign out — the token is simply presented as
// the Authorization header and PostgREST accepts it on its signature.
//
// Fixed at construction rather than swapped later, which is why entering and
// leaving demo mode both reload (see `demo.ts`). `persistSession` and
// `autoRefreshToken` are off so a demo visit cannot outlive its tab.
const demo = demoToken();

export const supabase = demo
  ? createClient(url ?? "", anonKey ?? "", {
      global: { headers: { Authorization: `Bearer ${demo}` } },
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    })
  : createClient(url ?? "", anonKey ?? "");
