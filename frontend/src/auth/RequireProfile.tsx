import { Center, Loader } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./useAuth";
import { useProfile } from "./profile";

export function RequireProfile({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  const profile = useProfile(session?.user.id);
  if (profile.isLoading) return <Center h="100vh"><Loader /></Center>;
  if (!profile.data) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/onboarding?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}
