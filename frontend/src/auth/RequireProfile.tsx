import { Center, Loader } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { isDemo } from "../lib/demo";
import { useAuth } from "./useAuth";
import { useProfile } from "./profile";

export function RequireProfile({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  const profile = useProfile(session?.user.id);
  // The demo principal has no account and therefore no `user_profiles` row;
  // asking it to complete onboarding would send a visitor to a form that writes
  // to a database that refuses it.
  if (isDemo()) return <>{children}</>;
  if (profile.isLoading) return <Center h="100vh"><Loader /></Center>;
  if (!profile.data) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/onboarding?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}
