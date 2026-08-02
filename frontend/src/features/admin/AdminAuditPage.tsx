// Audit log (AD-5): what administrators did.
//
// Read-only because the table itself is append-only — `admin_audit_log` refuses
// UPDATE and DELETE by trigger, including for `service_role`, which is what the
// router runs as. There is nothing to offer here but reading.
import { Badge, Card, Group, Loader, Stack, Table, Text, Title } from "@mantine/core";

import { useAuditLog } from "./api";

const DESTRUCTIVE = ["user.delete", "user.suspend", "admin.revoke", "job.cancel"];

export function AdminAuditPage() {
  const audit = useAuditLog();

  return (
    <Stack gap="md">
      <Title order={2}>Audit log</Title>

      <Card padding={0} radius="md" withBorder>
        {audit.isPending && (
          <Group p="md">
            <Loader size="sm" />
          </Group>
        )}
        {audit.data?.length === 0 && (
          <Text p="md" size="sm" c="dimmed">
            No admin actions recorded yet.
          </Text>
        )}
        {audit.data && audit.data.length > 0 && (
          <Table.ScrollContainer minWidth={640}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Action</Table.Th>
                  <Table.Th>Target</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {audit.data.map((entry) => (
                  <Table.Tr key={entry.id}>
                    <Table.Td>
                      <Text size="xs" ff="monospace" c="dimmed">
                        {new Date(entry.occurred_at).toLocaleString()}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge
                        size="sm"
                        variant="light"
                        color={DESTRUCTIVE.includes(entry.action) ? "red" : "gray"}
                      >
                        {entry.action}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {entry.target_label ?? entry.target_id?.slice(0, 8) ?? "—"}
                      </Text>
                      {entry.target_type && (
                        <Text size="xs" c="dimmed">
                          {entry.target_type}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {/* Whether they were standing in a Hunt they do not belong
                          to changes how the action should be read, and it cannot
                          be reconstructed later. */}
                      {entry.via_ghost_view && (
                        <Badge size="xs" variant="light" color="accent">
                          ghost view
                        </Badge>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>

      <Text size="xs" c="dimmed">
        Append-only: the table refuses UPDATE and DELETE by trigger, including for the service role
        the admin router itself runs as.
      </Text>
    </Stack>
  );
}
