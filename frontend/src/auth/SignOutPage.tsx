import { Center, Loader } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { supabase } from "../lib/supabase";

export function SignOutPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    void supabase.auth.signOut({ scope: "local" }).finally(() => {
      queryClient.clear();
      navigate("/login", { replace: true });
    });
  }, [navigate, queryClient]);

  return (
    <Center h="100vh" aria-label="Signing out">
      <Loader />
    </Center>
  );
}
