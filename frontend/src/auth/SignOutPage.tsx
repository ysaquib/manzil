import { Center, Loader } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { supabase } from "../lib/supabase";
import { nextQuery } from "./returnTo";

export function SignOutPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const started = useRef(false);
  // Signing out mid-flow is usually "wrong account, let me fix that" rather
  // than "I am done" — an invitation opened in a browser already signed in as
  // someone else. Carrying `next` through means the correct account lands back
  // on the invitation instead of the homepage.
  const next = nextQuery(params.get("next"));

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    void supabase.auth.signOut({ scope: "local" }).finally(() => {
      queryClient.clear();
      navigate(`/login${next}`, { replace: true });
    });
  }, [navigate, next, queryClient]);

  return (
    <Center h="100vh" aria-label="Signing out">
      <Loader />
    </Center>
  );
}
