// App frame (P1-9): Mantine AppShell, hunt-scoped nav, sign-out. Below the sm
// breakpoint the navbar collapses behind a Burger — every route stays
// reachable at phone width (frontend/AGENTS.md responsive rule).
import { AppShell, Burger, Button, Group, NavLink, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Link, NavLink as RouterNavLink, Outlet, useParams } from "react-router-dom";

import { supabase } from "../lib/supabase";

const NAV = [
  { label: "Overview", to: "" },
  { label: "Rubric", to: "rubric" },
  { label: "Tasks", to: "tasks" },
  { label: "Settings", to: "settings" },
];

export function AppLayout() {
  const { huntId } = useParams();
  const [navOpened, { toggle, close }] = useDisclosure(false);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 200, breakpoint: "sm", collapsed: { mobile: !navOpened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={navOpened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Link to="/" style={{ textDecoration: "none", color: "inherit" }}>
              <Title order={4}>Manzil</Title>
            </Link>
          </Group>
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
              onClick={close}
            />
          ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
