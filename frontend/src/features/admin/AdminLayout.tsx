// Admin panel shell (AD-2). Routes live at /admin/*, outside the /h/:huntId
// tree, because none of it is Hunt-scoped.
//
// The guard here is UX, not enforcement: every route the panel calls is gated
// server-side by `require_site_admin`, and the tables behind them have no client
// SELECT policy. Redirecting a non-admin away is about not showing them a shell
// full of 403s, not about keeping them out — that is the API's job.
import { Badge, Group, Loader, Stack, Text } from "@mantine/core";
import {
  IconClipboardList,
  IconCoin,
  IconGauge,
  IconListCheck,
  IconMessage2,
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
];

const OPERATIONS_ITEMS: RailItem[] = [
  { to: "/admin/costs", label: "Costs", icon: IconCoin },
  { to: "/admin/system", label: "System", icon: IconServer2 },
  { to: "/admin/audit", label: "Audit log", icon: IconShieldLock },
];

function RailLink({ item, count }: { item: RailItem; count?: number }) {
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

  return (
    <div className={classes.shell}>
      <nav className={classes.rail} aria-label="Admin sections">
        <div className={classes.railHead}>
          <Text
            component={Link}
            to="/"
            size="sm"
            fw={600}
            style={{ textDecoration: "none", color: "inherit" }}
          >
            ← Manzil
          </Text>
          {identity.data.is_primordial && (
            <Badge size="xs" variant="light" color="accent">
              owner
            </Badge>
          )}
        </div>

        <div className={classes.groupLabel}>Admin</div>
        {ADMIN_ITEMS.map((item) => (
          <RailLink
            key={item.to}
            item={item}
            count={item.to === "/admin/feedback" ? counts.data?.new : undefined}
          />
        ))}

        <div className={classes.groupLabel}>Operations</div>
        {OPERATIONS_ITEMS.map((item) => (
          <RailLink key={item.to} item={item} />
        ))}
      </nav>

      <main className={classes.main}>
        <Stack gap="lg">
          <Outlet />
        </Stack>
      </main>
    </div>
  );
}
