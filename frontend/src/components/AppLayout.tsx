// App frame (P1-9): Mantine AppShell, hunt-scoped nav, account menu. Below the
// sm breakpoint the navbar collapses behind a Burger — every route stays
// reachable at phone width (frontend/AGENTS.md responsive rule).
import { Anchor, AppShell, Badge, Burger, Group, NavLink, Title } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import {
  IconArrowsLeftRight,
  IconLayoutDashboard,
  IconListCheck,
  IconScale,
  IconSettings,
} from "@tabler/icons-react";
import { Link, NavLink as RouterNavLink, Outlet, useLocation, useParams } from "react-router-dom";

import { useHuntRealtime } from "../lib/realtime";
import { useCompareSet } from "../features/listings/compareSet";
import { CreateRubricPrompt } from "../features/rubric/CreateRubricPrompt";
import { ColorSchemeToggle } from "./ColorSchemeToggle";
import { UserMenu } from "./UserMenu";

const NAV = [
  { label: "Overview", to: "", icon: IconLayoutDashboard },
  { label: "Compare", to: "compare", icon: IconArrowsLeftRight },
  { label: "Rubric", to: "rubric", icon: IconScale },
  { label: "Tasks", to: "tasks", icon: IconListCheck },
  { label: "Settings", to: "settings", icon: IconSettings },
] as const;

function isNavActive(pathname: string, huntId: string, itemTo: string): boolean {
  const base = `/h/${huntId}`;
  if (itemTo === "") return pathname === base || pathname === `${base}/`;
  return pathname === `${base}/${itemTo}` || pathname.startsWith(`${base}/${itemTo}/`);
}

export function AppLayout() {
  const { huntId } = useParams();
  const location = useLocation();
  const [navOpened, { toggle, close }] = useDisclosure(false);
  const isMobile = useMediaQuery("(max-width: 48em)");
  useHuntRealtime(huntId);
  const compare = useCompareSet(huntId ?? "");

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
            <Anchor component={Link} to="/" c="inherit">
              <Title order={4}>Manzil</Title>
            </Anchor>
          </Group>
          <Group gap="sm">
            <ColorSchemeToggle size={isMobile ? "md" : "sm"} />
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {huntId &&
          NAV.map((item) => {
            const active = isNavActive(location.pathname, huntId, item.to);
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to || "overview"}
                component={RouterNavLink}
                to={`/h/${huntId}/${item.to}`}
                end={item.to === ""}
                label={item.label}
                active={active}
                variant="light"
                leftSection={<Icon size={18} stroke={1.5} />}
                rightSection={
                  item.to === "compare" && compare.entries.length > 0 ? (
                    <Badge size="sm" variant="light" circle>
                      {compare.entries.length}
                    </Badge>
                  ) : undefined
                }
                onClick={close}
                h={isMobile ? 64 : undefined}
                style={{
                  borderInlineStart: active
                    ? "3px solid var(--mantine-primary-color-filled)"
                    : "3px solid transparent",
                }}
              />
            );
          })}
      </AppShell.Navbar>
      <AppShell.Main>
        {huntId && <CreateRubricPrompt huntId={huntId} />}
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
