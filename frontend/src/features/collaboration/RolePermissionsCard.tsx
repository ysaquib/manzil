// "Your role and permissions" (P3-16, DESIGN §20 v3.27) — shown to every role,
// Owner included. Names the mechanism outright ("role", "permissions") because
// the vocabulary is what someone needs in order to ask for more, and splits
// permitted from withheld so an Owner reads a complete picture rather than a
// wall of green.
import { Badge, Group, Stack, Text } from "@mantine/core";
import { IconCheck, IconMinus } from "@tabler/icons-react";

import { SectionCard } from "../../components/SectionCard";
import { rolePermissions, type HuntRole, type RolePermission } from "./rolePermissions";

function PermissionList({
  permissions,
  tone,
}: {
  permissions: RolePermission[];
  tone: "permitted" | "withheld";
}) {
  const Icon = tone === "permitted" ? IconCheck : IconMinus;
  return (
    <Stack gap={4}>
      {permissions.map((permission) => (
        <Group key={`${permission.label}${permission.scope ?? ""}`} gap={8} wrap="nowrap">
          <Icon
            size={14}
            stroke={2}
            color={
              tone === "permitted"
                ? "var(--mantine-color-green-filled)"
                : "var(--mantine-color-dimmed)"
            }
            style={{ flex: "none", marginTop: 3 }}
          />
          <Text size="sm" c={tone === "permitted" ? undefined : "dimmed"} lh={1.4}>
            {permission.label}
            {permission.scope && (
              <Text span size="xs" c="dimmed">
                {" "}
                {permission.scope}
              </Text>
            )}
          </Text>
        </Group>
      ))}
    </Stack>
  );
}

export function RolePermissionsCard({
  role,
  ownerName,
}: {
  role: HuntRole;
  /** Who to ask for a different role — omitted when the reader is the Owner. */
  ownerName?: string;
}) {
  const { roleLabel, permitted, withheld, withheldNote } = rolePermissions(role);

  return (
    <SectionCard title="Your role and permissions" hint="Set by the Owner">
      <Stack gap="md">
        {/* `component="div"`: Mantine's Text is a <p> by default, and Badge
            renders a <div> — nesting one in the other is invalid HTML. */}
        <Text component="div" size="sm" c="dimmed" lh={1.5}>
          Your role in this hunt is{" "}
          <Badge variant="light" color={role === "owner" ? "primary" : "gray"}>
            {roleLabel}
          </Badge>
          . A role is a bundle of permissions — it decides which controls you can use here.
        </Text>

        <Stack gap={6}>
          <Text size="xs" fw={700} c="green" tt="uppercase" style={{ letterSpacing: "0.08em" }}>
            The {roleLabel} role permits
          </Text>
          <PermissionList permissions={permitted} tone="permitted" />
        </Stack>

        <Stack gap={6}>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: "0.08em" }}>
            Not permitted by this role
          </Text>
          {withheld.length === 0 ? (
            <Text size="sm" c="dimmed" lh={1.5}>
              {withheldNote}
            </Text>
          ) : (
            <>
              <PermissionList permissions={withheld} tone="withheld" />
              <Text size="xs" c="dimmed" lh={1.5}>
                Ask {ownerName ?? "the Owner"} to change your role if you need one of these.
              </Text>
            </>
          )}
        </Stack>
      </Stack>
    </SectionCard>
  );
}
