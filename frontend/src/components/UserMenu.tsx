// Account menu (header chrome): avatar in the user's default color opening
// Profile + Sign out. Shared by the in-hunt AppShell header and the hunt
// switcher so the profile page is reachable from anywhere.
import { Avatar, Menu, UnstyledButton } from "@mantine/core";
import { IconLogout, IconSettings, IconUserCircle } from "@tabler/icons-react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { useProfile } from "../auth/profile";
import { memberColor } from "../features/collaboration/memberColors";

export function UserMenu() {
  const { session } = useAuth();
  const profile = useProfile(session?.user.id);
  const name = profile.data?.default_display_name ?? session?.user.email ?? "";
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  const background = memberColor(profile.data?.default_color ?? null);

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <UnstyledButton aria-label="account menu" style={{ display: "flex" }}>
          <Avatar
            size={30}
            radius="xl"
            styles={{
              placeholder: {
                backgroundColor: background,
                color: "var(--mantine-color-white)",
              },
            }}
          >
            {initial}
          </Avatar>
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        {name && <Menu.Label>{name}</Menu.Label>}
        <Menu.Item
          component={Link}
          to="/account/profile"
          leftSection={<IconUserCircle size={14} stroke={1.5} />}
        >
          Profile
        </Menu.Item>
        <Menu.Item
          component={Link}
          to="/account/security"
          leftSection={<IconSettings size={14} stroke={1.5} />}
        >
          Account settings
        </Menu.Item>
        <Menu.Item
          component={Link}
          to="/signout"
          leftSection={<IconLogout size={14} stroke={1.5} />}
        >
          Sign out
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
