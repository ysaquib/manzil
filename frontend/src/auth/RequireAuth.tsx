// Route guard (Phase 1 plan §5.2): redirects to /login when there's no session.
//
// The redirect carries where you were going as `?next=`, not only as router
// state, because router state dies the moment the login page is reloaded,
// re-opened in another tab, or reached by any path other than this redirect —
// and losing it means an invite link silently becomes "you are now at the
// homepage", which reads as a broken invitation.
import { Center, Loader } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { isDemo } from "../lib/demo";
import { nextQuery } from "./returnTo";
import { useAuth } from "./useAuth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();
  // A demo visitor is authenticated by a server-minted token with no
  // `auth.users` row behind it (DESIGN §20 v3.55), so GoTrue has no session to
  // report and this guard would bounce them straight back to /login — the page
  // they entered the demo from.
  if (isDemo()) return <>{children}</>;
  if (loading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  const from = `${location.pathname}${location.search}`;
  if (!session) return <Navigate to={`/login${nextQuery(from)}`} replace state={{ from }} />;
  return <>{children}</>;
}
