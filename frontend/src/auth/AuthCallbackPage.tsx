import { Center, Loader } from "@mantine/core";
import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "./useAuth";

export function AuthCallbackPage() {
  const { session, loading } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  useEffect(() => { if (!loading && session) navigate(params.get("next") || "/", { replace: true }); }, [loading, navigate, params, session]);
  return <Center h="100vh"><Loader /></Center>;
}
