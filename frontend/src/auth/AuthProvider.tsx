// Session context (Phase 1 plan §5.2): tracks the Supabase auth session via
// onAuthStateChange. Phase 1 is one user (magic-link); no password-reset flow.
import type { Session } from "@supabase/supabase-js";
import { createContext, useEffect, useState, type ReactNode } from "react";

import { supabase } from "../lib/supabase";

export interface AuthState {
  session: Session | null;
  loading: boolean;
}

export const AuthContext = createContext<AuthState>({ session: null, loading: true });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });
    return () => subscription.unsubscribe();
  }, []);

  return <AuthContext.Provider value={{ session, loading }}>{children}</AuthContext.Provider>;
}
