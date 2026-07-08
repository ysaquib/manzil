// App frame (Phase 1 plan P1-9): Mantine AppShell, hunt-scoped nav, sign-out.
// The hunt switcher itself lands with the hunts feature (P1-9); this is the
// stable chrome every hunt route renders inside.
import { AppShell, Button, Group, NavLink, Title } from "@mantine/core";
import { NavLink as RouterNavLink, Outlet, useParams } from "react-router-dom";

import { supabase } from "../lib/supabase";

const NAV = [
  { label: "Overview", to: "" },
  { label: "Rubric", to: "rubric" },
  { label: "Tasks", to: "tasks" },
  { label: "Settings", to: "settings" },
];

export function AppLayout() {
  const { huntId } = useParams();

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 200, breakpoint: "sm" }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={4}>Manzil</Title>
          <Button variant="subtle" size="xs" onClick={() => supabase.auth.signOut()}>
            Sign out
          </Button>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {huntId &&
          NAV.map((item) => (
            <NavLink
              key={item.to || "overview"}
              component={RouterNavLink}
              to={`/h/${huntId}/${item.to}`}
              end={item.to === ""}
              label={item.label}
            />
          ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
