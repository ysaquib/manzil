import { Center, Loader } from "@mantine/core";
import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { safeReturnTo } from "./returnTo";
import { useAuth } from "./useAuth";

export function AuthCallbackPage() {
  const { session, loading } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  // `next` arrives from a link that has been out of the app's hands — through an
  // email client and back — so it is filtered rather than followed.
  useEffect(() => {
    if (!loading && session) navigate(safeReturnTo(params.get("next")), { replace: true });
  }, [loading, navigate, params, session]);
  return <Center h="100vh"><Loader /></Center>;
}
