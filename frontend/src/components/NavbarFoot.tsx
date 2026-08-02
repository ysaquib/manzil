// Navbar foot (P3-16, DESIGN §20 v3.27): Submit feedback above the account
// cluster, pinned to the bottom of the hunt navbar.
//
// The cluster expands *in place* rather than opening a floating dropdown —
// nothing overlays what the reader was looking at — and it carries the email
// address, which is the one fact that answers "which account am I in?" without
// a click. Below `sm` the navbar hides behind the Burger, so AppLayout keeps the
// header `UserMenu` at that breakpoint and this component is not rendered.
import { Avatar, Box, Collapse, Group, Stack, Text, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconChevronUp,
  IconLogout,
  IconMessage2,
  IconShieldLock,
  IconSettings,
  IconUserCircle,
} from "@tabler/icons-react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { useProfile } from "../auth/profile";
import { useAdminIdentity } from "../features/admin/api";
import { memberColor } from "../features/collaboration/memberColors";
import classes from "./NavbarFoot.module.css";

export function NavbarFoot({ onOpenFeedback }: { onOpenFeedback: () => void }) {
  const { session } = useAuth();
  const profile = useProfile(session?.user.id);
  const [expanded, { toggle }] = useDisclosure(false);
  // UX only: every admin route is gated server-side, and the tables behind them
  // have no client SELECT policy. This just avoids showing a door that opens
  // onto a wall (AGENTS.md: frontend checks are never enforcement).
  const admin = useAdminIdentity();

  const email = session?.user.email ?? "";
  const name = profile.data?.default_display_name ?? email;
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const background = memberColor(profile.data?.default_color ?? null);

  return (
    <Box className={classes.foot}>
      {admin.data?.is_site_admin && (
        <UnstyledButton component={Link} to="/admin" className={classes.admin}>
          <IconShieldLock size={16} stroke={1.6} className={classes.adminIcon} />
          <Text size="sm">Admin panel</Text>
        </UnstyledButton>
      )}

      <UnstyledButton className={classes.feedback} onClick={onOpenFeedback}>
        <IconMessage2 size={16} stroke={1.6} className={classes.feedbackIcon} />
        <Text size="sm">Submit feedback</Text>
      </UnstyledButton>

      <UnstyledButton
        className={classes.account}
        onClick={toggle}
        aria-expanded={expanded}
        aria-label="account menu"
      >
        <Group gap="xs" wrap="nowrap">
          <Avatar
            size={28}
            radius="xl"
            styles={{
              placeholder: { backgroundColor: background, color: "var(--mantine-color-white)" },
            }}
          >
            {initial}
          </Avatar>
          <Stack gap={0} className={classes.identity}>
            <Text size="sm" fw={600} lh={1.25} truncate>
              {name}
            </Text>
            {email && email !== name && (
              <Text size="xs" c="dimmed" lh={1.3} truncate>
                {email}
              </Text>
            )}
          </Stack>
          <IconChevronUp
            size={15}
            stroke={1.8}
            className={classes.chevron}
            data-expanded={expanded || undefined}
          />
        </Group>
      </UnstyledButton>

      <Collapse expanded={expanded}>
        <Stack gap={1} pt={4}>
          <UnstyledButton component={Link} to="/account/profile" className={classes.item}>
            <IconUserCircle size={15} stroke={1.6} />
            <Text size="sm">Profile</Text>
          </UnstyledButton>
          <UnstyledButton component={Link} to="/account/security" className={classes.item}>
            <IconSettings size={15} stroke={1.6} />
            <Text size="sm">Account settings</Text>
          </UnstyledButton>
          <UnstyledButton component={Link} to="/signout" className={classes.itemDanger}>
            <IconLogout size={15} stroke={1.6} />
            <Text size="sm">Sign out</Text>
          </UnstyledButton>
        </Stack>
      </Collapse>
    </Box>
  );
}
