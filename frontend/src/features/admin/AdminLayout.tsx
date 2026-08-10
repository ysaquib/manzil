// Admin panel shell (AD-2). Routes live at /admin/*, outside the /h/:huntId
// tree, because none of it is Hunt-scoped.
//
// The guard here is UX, not enforcement: every route the panel calls is gated
// server-side by `require_site_admin`, and the tables behind them have no client
// SELECT policy. Redirecting a non-admin away is about not showing them a shell
// full of 403s, not about keeping them out — that is the API's job.
import { Badge, Burger, Drawer, Group, Loader, Stack, Text } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import {
  IconClipboardList,
  IconCoin,
  IconGauge,
  IconListCheck,
  IconMessage2,
  IconPresentation,
  IconServer2,
  IconShieldLock,
  IconUsers,
} from "@tabler/icons-react";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";

import { useAdminIdentity, useFeedbackCounts } from "./api";
import classes from "./AdminLayout.module.css";

interface RailItem {
  to: string;
  label: string;
  icon: typeof IconGauge;
  /** Slice that will build it — rendered disabled until then. */
  pending?: string;
}

const ADMIN_ITEMS: RailItem[] = [
  { to: "/admin", label: "Overview", icon: IconGauge },
  { to: "/admin/people", label: "People", icon: IconUsers },
  { to: "/admin/hunts", label: "Hunts", icon: IconClipboardList },
  { to: "/admin/jobs", label: "Jobs", icon: IconListCheck },
  { to: "/admin/feedback", label: "Feedback", icon: IconMessage2 },
  { to: "/admin/demo", label: "Demo Mode", icon: IconPresentation },
];

const OPERATIONS_ITEMS: RailItem[] = [
  { to: "/admin/costs", label: "Costs", icon: IconCoin },
  { to: "/admin/system", label: "System", icon: IconServer2 },
  { to: "/admin/audit", label: "Audit log", icon: IconShieldLock },
];

/** The section the current path is in — the phone header's only title. */
function activeItem(pathname: string): RailItem | undefined {
  const all = [...ADMIN_ITEMS, ...OPERATIONS_ITEMS];
  if (pathname === "/admin") return all[0];
  return all.find((item) => item.to !== "/admin" && pathname.startsWith(item.to));
}

function RailLink({
  item,
  count,
  onNavigate,
}: {
  item: RailItem;
  count?: number;
  /** Closes the phone drawer — a nav that stays open over the page it opened is worse than none. */
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  const location = useLocation();

  if (item.pending) {
    return (
      <span
        className={`${classes.item} ${classes.itemPending}`}
        title={`Not built yet — ${item.pending}`}
        aria-disabled="true"
      >
        <Icon size={17} stroke={1.5} />
        {item.label}
        <span className={classes.count}>{item.pending}</span>
      </span>
    );
  }

  // `end` on the index route only, so /admin does not stay lit on /admin/feedback.
  const active =
    item.to === "/admin"
      ? location.pathname === "/admin"
      : location.pathname.startsWith(item.to);

  return (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      className={`${classes.item} ${active ? classes.itemActive : ""}`}
    >
      <Icon size={17} stroke={1.5} />
      {item.label}
      {count !== undefined && count > 0 && <span className={classes.count}>{count}</span>}
    </NavLink>
  );
}

export function AdminLayout() {
  const identity = useAdminIdentity();
  const counts = useFeedbackCounts(identity.data?.is_site_admin === true);
  const location = useLocation();
  // The rail is eight links in two labelled groups. Wrapping it into pill rows
  // above the content — the old phone treatment — lost the grouping, ate a
  // third of the viewport, and read as a bag of tags rather than a navigation.
  // Below `sm` it becomes what the rest of the app already uses: a Burger and a
  // drawer, with the section name in the bar so the page still says where it is.
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;
  const [navOpened, { toggle, close }] = useDisclosure(false);

  if (identity.isPending) {
    return (
      <Group justify="center" p="xl">
        <Loader size="sm" />
      </Group>
    );
  }

  // Also covers the error case: if /admin/me could not be reached we have no
  // reason to believe the caller is an admin, and guessing yes would render a
  // panel that only produces failures.
  if (!identity.data?.is_site_admin) {
    return <Navigate to="/" replace />;
  }

  const onNavigate = isCompact ? close : undefined;
  const sections = (
    <>
      <div className={classes.groupLabel}>Admin</div>
      {ADMIN_ITEMS.map((item) => (
        <RailLink
          key={item.to}
          item={item}
          onNavigate={onNavigate}
          count={item.to === "/admin/feedback" ? counts.data?.new : undefined}
        />
      ))}

      <div className={classes.groupLabel}>Operations</div>
      {OPERATIONS_ITEMS.map((item) => (
        <RailLink key={item.to} item={item} onNavigate={onNavigate} />
      ))}
    </>
  );

  const homeLink = (
    <Text
      component={Link}
      to="/"
      size="sm"
      fw={600}
      style={{ textDecoration: "none", color: "inherit" }}
    >
      ← Manzil
    </Text>
  );

  const ownerBadge = identity.data.is_primordial && (
    <Badge size="xs" variant="light" color="accent">
      owner
    </Badge>
  );

  return (
    <div className={classes.shell}>
      {isCompact ? (
        <>
          <header className={classes.mobileBar}>
            <Burger
              opened={navOpened}
              onClick={toggle}
              size="sm"
              aria-label="Admin sections"
            />
            <Text fw={600} size="sm" className={classes.mobileTitle}>
              {activeItem(location.pathname)?.label ?? "Admin"}
            </Text>
            {ownerBadge}
            {homeLink}
          </header>
          <Drawer
            opened={navOpened}
            onClose={close}
            size="16rem"
            padding={0}
            withCloseButton={false}
            title={null}
            classNames={{ content: classes.drawerContent, body: classes.drawerBody }}
          >
            <nav className={classes.rail} aria-label="Admin sections">
              <div className={classes.railHead}>{homeLink}</div>
              {sections}
            </nav>
          </Drawer>
        </>
      ) : (
        <nav className={classes.rail} aria-label="Admin sections">
          <div className={classes.railHead}>
            {homeLink}
            {ownerBadge}
          </div>
          {sections}
        </nav>
      )}

      <main className={classes.main}>
        <Stack gap="lg">
          <Outlet />
        </Stack>
      </main>
    </div>
  );
}
