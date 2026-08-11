// App frame (P1-9; reworked by P3-16, DESIGN §20 v3.27): Mantine AppShell with
// the hunt name centered in the header as a switcher, and the account cluster
// moved out of the header to the bottom of the navbar — where there is room for
// the email address.
//
// Below the sm breakpoint the navbar collapses behind a Burger, so the account
// cluster is only reachable after opening it; at that width the header keeps the
// original `UserMenu` as the always-available path. Both offer the same three
// items, so nothing is reachable at only one size.
import {
  Anchor,
  AppShell,
  Badge,
  Box,
  Burger,
  Group,
  Menu,
  NavLink,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";

import { DemoBanner } from "../features/demo/DemoBanner";
import { isDemo } from "../lib/demo";
import {
  IconArrowsLeftRight,
  IconChevronDown,
  IconFlag,
  IconLayoutDashboard,
  IconListCheck,
  IconMap2,
  IconScale,
  IconSettings,
} from "@tabler/icons-react";
import { Link, NavLink as RouterNavLink, Outlet, useLocation, useParams } from "react-router-dom";

import { useHuntRealtime } from "../lib/realtime";
import { useCompareSet } from "../features/listings/compareSet";
import { useAttention } from "../features/notifications/api";
import { OverviewFiltersProvider } from "../features/listings/filterState";
import { GhostBanner } from "../features/admin/GhostBanner";
import { useGhostMode } from "../features/admin/useGhostMode";
import { FeedbackModal } from "../features/feedback/FeedbackModal";
import { FeedbackProvider } from "../features/feedback/FeedbackContext";
import { CreateRubricPrompt } from "../features/rubric/CreateRubricPrompt";
import { useHunt, useHunts } from "../features/hunts/api";
import { useHuntAccess } from "../features/hunts/access";
import { HuntStateBanner } from "../features/hunts/HuntStateBanner";
import { ColorSchemeToggle } from "./ColorSchemeToggle";
import { NavbarFoot } from "./NavbarFoot";
import { UserMenu } from "./UserMenu";
import classes from "./AppLayout.module.css";

const NAV = [
  { label: "Overview", to: "", icon: IconLayoutDashboard },
  { label: "Map", to: "map", icon: IconMap2 },
  { label: "Compare", to: "compare", icon: IconArrowsLeftRight },
  { label: "Visits", to: "visits", icon: IconFlag },
  { label: "Rubric", to: "rubric", icon: IconScale },
  { label: "Tasks", to: "tasks", icon: IconListCheck },
  { label: "Settings", to: "settings", icon: IconSettings },
] as const;

function isNavActive(pathname: string, huntId: string, itemTo: string): boolean {
  const base = `/h/${huntId}`;
  if (itemTo === "") return pathname === base || pathname === `${base}/`;
  return pathname === `${base}/${itemTo}` || pathname.startsWith(`${base}/${itemTo}/`);
}

/** Centered hunt name; the chevron opens the other hunts plus the switcher. */
function HuntSwitcher({ huntId }: { huntId: string }) {
  const { data: hunt } = useHunt(huntId);
  const { data: hunts = [] } = useHunts();
  const others = hunts.filter((candidate) => candidate.id !== huntId);

  if (!hunt) return null;

  return (
    <Menu position="bottom" withinPortal shadow="md">
      <Menu.Target>
        <UnstyledButton className={classes.huntSwitch} aria-label="switch hunt">
          <Text component="span" className={classes.huntName}>
            {hunt.name}
          </Text>
          <IconChevronDown size={13} stroke={1.8} className={classes.huntChevron} />
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        {others.length > 0 && <Menu.Label>Switch to</Menu.Label>}
        {others.map((candidate) => (
          <Menu.Item key={candidate.id} component={Link} to={`/h/${candidate.id}`}>
            {candidate.name}
          </Menu.Item>
        ))}
        {others.length > 0 && <Menu.Divider />}
        <Menu.Item component={Link} to="/">
          All hunts…
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

export function AppLayout() {
  const { huntId } = useParams();
  const location = useLocation();
  const [navOpened, { toggle, close }] = useDisclosure(false);
  const [feedbackOpened, { open: openFeedback, close: closeFeedback }] = useDisclosure(false);
  const isMobile = useMediaQuery("(max-width: 48em)");
  useHuntRealtime(huntId);
  const compare = useCompareSet(huntId ?? "");
  const { data: attention } = useAttention(huntId ?? "");
  // AD-4: a Site Admin reading a Hunt they do not belong to. Derived from
  // membership, so it is correct on every screen without any route state.
  const { isGhost } = useGhostMode(huntId);
  const { data: ghostHunt } = useHunt(huntId ?? "");
  const access = useHuntAccess(huntId ?? "");

  return (
    <>
      {isDemo() && <DemoBanner />}
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 224, breakpoint: "sm", collapsed: { mobile: !navOpened } }}
      padding="md"
    >
      <AppShell.Header>
        <div className={classes.header}>
          <Group gap="sm" wrap="nowrap">
            <Burger opened={navOpened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Anchor component={Link} to="/" c="inherit" underline="never">
              <Title order={4}>Manzil</Title>
            </Anchor>
          </Group>
          <div className={classes.headerCenter}>{huntId && <HuntSwitcher huntId={huntId} />}</div>
          <Group gap="sm" wrap="nowrap" justify="flex-end">
            <ColorSchemeToggle size={isMobile ? "md" : "sm"} />
            {/* The navbar foot owns the account cluster on desktop; at phone
                width the navbar is behind the Burger, so the header keeps it. */}
            {isMobile && <UserMenu />}
          </Group>
        </div>
      </AppShell.Header>

      <AppShell.Navbar p="xs" className={classes.navbar}>
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
                  ) : item.to === "tasks" && attention?.task_status ? (
                    <Tooltip
                      label={`${attention[attention.task_status]} ${attention.task_status.replace("_", " ")} Jobs`}
                    >
                      <Box
                        component="span"
                        role="img"
                        aria-label={`${attention[attention.task_status]} ${attention.task_status.replace("_", " ")} Jobs`}
                        w={9}
                        h={9}
                        style={{
                          borderRadius: "50%",
                          background:
                            attention.task_status === "failed"
                              ? "var(--mantine-color-red-6)"
                              : attention.task_status === "waiting_user"
                                ? "var(--mantine-color-yellow-6)"
                                : "var(--mantine-color-violet-6)",
                        }}
                      />
                    </Tooltip>
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

        <div className={classes.navSpacer} />
        {/* Rendered at every width — inside an opened navbar it works on a phone
            too. The header UserMenu above is the always-reachable path when the
            navbar is collapsed, not a replacement for this. */}
        <NavbarFoot onOpenFeedback={openFeedback} />
      </AppShell.Navbar>

      <AppShell.Main className={classes.main}>
        {isGhost === true && <GhostBanner huntName={ghostHunt?.name} />}
        <HuntStateBanner reason={access.state} adminOverride={access.adminArchivedOverride} />
        {huntId && access.canMutate && <CreateRubricPrompt huntId={huntId} />}
        {/* Filter state lives above the Outlet so Overview and Map filter the
            same set; keying on huntId re-seeds hunt-wide filters on switch. */}
        <OverviewFiltersProvider key={huntId ?? ""} huntId={huntId ?? ""}>
          <FeedbackProvider openFeedback={openFeedback}>
            <Outlet />
          </FeedbackProvider>
        </OverviewFiltersProvider>
      </AppShell.Main>

      <FeedbackModal opened={feedbackOpened} onClose={closeFeedback} />
    </AppShell>
    </>
  );
}
