// supabase-js client (Phase 1 plan §1.6): auth session + direct RLS-guarded
// reads of continuously-rendered table data. Mutations go through apiClient.ts.
import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  // Fail loud in dev — a missing anon key silently breaks every read.
  console.warn("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY not set — see .env.example");
}

export const supabase = createClient(url ?? "", anonKey ?? "");
