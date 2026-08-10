// People (AD-3). Roster left, detail right — a person is almost always looked
// up in order to *do* something to them, so the detail sits beside the list
// rather than behind a navigation.
//
// The load-bearing UI decision: when someone owns a Hunt, Delete is disabled
// and the Hunts they own are listed next to it with a transfer control. The API
// refuses the delete either way; showing the reason before the click is what
// stops the operator hunting for it.
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Menu,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { IconAlertTriangle, IconDots, IconSearch, IconUserPlus } from "@tabler/icons-react";
import { useState } from "react";

import { TablePagination, usePagedRows } from "../../components/TablePagination";
import { HuntPicker } from "./HuntPicker";
import {
  useAdminPeople,
  useAdminPerson,
  useDeletePerson,
  useProvisionPerson,
  usePersonAction,
  useRemoveMembership,
  useSetMembership,
  type PersonRow,
} from "./api";

const ROLE_OPTIONS = [
  { value: "member", label: "Member" },
  { value: "curator", label: "Curator" },
  { value: "owner", label: "Owner" },
];

function StateBadges({ person }: { person: PersonRow }) {
  return (
    <Group gap={4}>
      {person.suspended ? (
        <Badge size="sm" color="red" variant="light">
          Suspended
        </Badge>
      ) : person.confirmed ? (
        <Badge size="sm" color="green" variant="light">
          Active
        </Badge>
      ) : (
        <Badge size="sm" color="yellow" variant="light">
          Invited
        </Badge>
      )}
      {person.is_site_admin && (
        <Badge size="sm" color="primary" variant="light">
          Admin
        </Badge>
      )}
    </Group>
  );
}

function PersonDetailPanel({ userId }: { userId: string }) {
  const person = useAdminPerson(userId);
  const action = usePersonAction();
  const setMembership = useSetMembership();
  const removeMembership = useRemoveMembership();
  const deletePerson = useDeletePerson();
  const [addHunt, setAddHunt] = useState<string | null>(null);
  const [addRole, setAddRole] = useState<string>("member");

  if (person.isPending) return <Loader size="sm" />;
  if (!person.data) return <Alert color="red">Could not load that account.</Alert>;

  const p = person.data;
  const blocked = p.blocking_owned_hunts.length > 0;

  return (
    <Stack gap="md">
      <Card padding="md" radius="md" withBorder>
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>{p.display_name ?? p.email ?? "Unknown"}</Title>
            <Text size="sm" c="dimmed" ff="monospace">
              {p.email}
            </Text>
          </Stack>
          <StateBadges person={p} />
        </Group>

        <Group gap="lg" mt="sm">
          <Text size="xs" c="dimmed">
            Joined {new Date(p.created_at).toLocaleDateString()}
          </Text>
          <Text size="xs" c="dimmed">
            Last seen{" "}
            {p.last_sign_in_at ? new Date(p.last_sign_in_at).toLocaleString() : "never"}
          </Text>
          <Text size="xs" c="dimmed">
            {p.feedback_count} report{p.feedback_count === 1 ? "" : "s"} filed
          </Text>
        </Group>

        <Group gap="xs" mt="md">
          <Button
            size="xs"
            variant="default"
            loading={action.isPending}
            onClick={() =>
              action.mutate({ userId, action: p.suspended ? "restore" : "suspend" })
            }
          >
            {p.suspended ? "Restore" : "Suspend"}
          </Button>
          <Button
            size="xs"
            variant="default"
            onClick={() => action.mutate({ userId, action: "password-reset" })}
          >
            Send password reset
          </Button>

          {/* Disabled with the reason attached, rather than enabled and then
              refused. The API refuses it regardless — this is about not making
              the operator go looking for why. */}
          <Tooltip
            label={
              blocked
                ? `They own ${p.blocking_owned_hunts.map((h) => h.hunt_name).join(", ")} — transfer it first`
                : "Permanently delete this account"
            }
          >
            <Button
              size="xs"
              color="red"
              variant="light"
              disabled={blocked}
              loading={deletePerson.isPending}
              onClick={() => deletePerson.mutate(userId)}
            >
              Delete
            </Button>
          </Tooltip>
        </Group>

        {blocked && (
          <Alert color="yellow" icon={<IconAlertTriangle size={16} />} mt="sm">
            Deleting them would take{" "}
            {p.blocking_owned_hunts.map((h) => h.hunt_name).join(", ")} and every Listing,
            Visit and Job under it. Transfer ownership below first.
          </Alert>
        )}
      </Card>

      <Card padding="md" radius="md" withBorder>
        <Title order={5} mb="xs">
          Memberships
        </Title>
        {p.memberships.length === 0 && (
          <Text size="sm" c="dimmed">
            Not a member of any Hunt.
          </Text>
        )}
        {p.memberships.length > 0 && (
          <Table striped={false} withRowBorders={false} verticalSpacing={6}>
            <Table.Tbody>
              {p.memberships.map((m) => (
                <Table.Tr key={m.hunt_id}>
                  <Table.Td>{m.hunt_name}</Table.Td>
                  <Table.Td w={140}>
                    <Select
                      size="xs"
                      data={ROLE_OPTIONS}
                      value={m.role}
                      allowDeselect={false}
                      onChange={(role) =>
                        role &&
                        setMembership.mutate({
                          userId,
                          huntId: m.hunt_id,
                          role: role as "owner" | "curator" | "member",
                        })
                      }
                    />
                  </Table.Td>
                  <Table.Td w={40}>
                    <Tooltip
                      label={
                        m.role === "owner"
                          ? "Transfer ownership before removing the Owner"
                          : "Remove from this Hunt"
                      }
                    >
                      <ActionIcon
                        size="sm"
                        variant="subtle"
                        color="red"
                        disabled={m.role === "owner"}
                        onClick={() =>
                          removeMembership.mutate({ userId, huntId: m.hunt_id })
                        }
                      >
                        ×
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}

        <Group gap="xs" mt="sm" align="flex-end" wrap="wrap">
          <HuntPicker
            placeholder="Add to a Hunt…"
            style={{ flex: 1, minWidth: 180 }}
            value={addHunt}
            onChange={(huntId) => setAddHunt(huntId)}
            clearable
          />
          <Select
            size="xs"
            w={110}
            data={ROLE_OPTIONS}
            value={addRole}
            allowDeselect={false}
            onChange={(v) => v && setAddRole(v)}
          />
          <Button
            size="xs"
            variant="default"
            disabled={!addHunt}
            onClick={() => {
              if (!addHunt) return;
              setMembership.mutate({
                userId,
                huntId: addHunt,
                role: addRole as "owner" | "curator" | "member",
              });
              setAddHunt(null);
            }}
          >
            Add
          </Button>
        </Group>
      </Card>
    </Stack>
  );
}

function ProvisionModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const provision = useProvisionPerson();
  const [email, setEmail] = useState("");
  const [huntId, setHuntId] = useState<string | null>(null);
  const [role, setRole] = useState("member");

  const submit = () => {
    if (!email.trim() || provision.isPending) return;
    provision.mutate(
      {
        email: email.trim(),
        ...(huntId ? { hunt_id: huntId, role } : {}),
      },
      {
        onSuccess: () => {
          setEmail("");
          setHuntId(null);
          onClose();
        },
      },
    );
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Create account" centered>
      {/* A one-field form: Enter submits it, because every other one-field form
          on the web does. */}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Stack gap="sm">
          <TextInput
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            placeholder="them@example.com"
          />
          {/* Optional: the invite creates the account, the Hunt is a separate
              fact. Conflating them is how you get a half-joined user. */}
          <HuntPicker
            size="sm"
            label="Add to a Hunt (optional)"
            placeholder="Search Hunts…"
            clearable
            value={huntId}
            onChange={(next) => setHuntId(next)}
          />
          {huntId && (
            <Select
              label="Role"
              data={ROLE_OPTIONS}
              value={role}
              allowDeselect={false}
              onChange={(v) => v && setRole(v)}
            />
          )}
          <Text size="sm" c="dimmed">
            They will receive a secure link to choose their password. Public registration is
            disabled.
          </Text>
          {provision.isError && (
            <Alert color="red">{(provision.error as Error).message}</Alert>
          )}
          <Button type="submit" disabled={!email.trim()} loading={provision.isPending}>
            Create account
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}

export function AdminPeoplePage() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [provisionOpen, { open: openProvision, close: closeProvision }] = useDisclosure(false);
  const people = useAdminPeople(search);
  // Phone width: the roster and the detail panel cannot sit side by side in
  // 24rem, so the panel moves under the list and only appears once someone is
  // picked. The placeholder card ("select someone") is desktop-only furniture.
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;
  const paged = usePagedRows(people.data ?? [], "admin-people");

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap" gap="xs">
        <Title order={2}>People</Title>
        {/* `1 1 100%` rather than `flex: 1`: the cluster has to take a whole
            row of its own under the title, not squeeze in beside it and wrap
            internally — which is what it did, leaving the title floating
            against a two-line stack. */}
        <Group
          gap="xs"
          wrap="nowrap"
          style={isCompact ? { flex: "1 1 100%" } : undefined}
        >
          <TextInput
            size="xs"
            placeholder="Search name or email…"
            leftSection={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            w={isCompact ? undefined : 220}
            style={isCompact ? { flex: 1 } : undefined}
          />
          <Button size="xs" leftSection={<IconUserPlus size={14} />} onClick={openProvision}>
            Create account
          </Button>
        </Group>
      </Group>

      <Group
        component="section"
        aria-label="People directory"
        align="flex-start"
        gap="md"
        wrap={isCompact ? "wrap" : "nowrap"}
      >
        <Card
          padding={0}
          radius="md"
          withBorder
          style={{ flex: 1, minWidth: 0, width: isCompact ? "100%" : undefined }}
        >
          {people.isPending && (
            <Group p="md">
              <Loader size="sm" />
            </Group>
          )}
          {people.data?.length === 0 && (
            <Text p="md" size="sm" c="dimmed">
              Nobody matches that search.
            </Text>
          )}
          {people.data && people.data.length > 0 && (
            <>
            <Table.ScrollContainer minWidth={520}>
              <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Person</Table.Th>
                    <Table.Th>State</Table.Th>
                    <Table.Th ta="end">Hunts</Table.Th>
                    <Table.Th ta="end">Spend</Table.Th>
                    <Table.Th w={40} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {paged.items.map((person) => (
                    <Table.Tr
                      key={person.user_id}
                      onClick={() => setSelected(person.user_id)}
                      style={{ cursor: "pointer" }}
                      bg={
                        selected === person.user_id
                          ? "var(--mantine-color-primary-light)"
                          : undefined
                      }
                    >
                      <Table.Td>
                        <Text size="sm" fw={600}>
                          {person.display_name ?? "—"}
                        </Text>
                        <Text size="xs" c="dimmed" ff="monospace">
                          {person.email}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <StateBadges person={person} />
                      </Table.Td>
                      <Table.Td ta="end" ff="monospace" fz="xs">
                        {person.hunts}
                        {person.owns > 0 && (
                          <Text span c="dimmed" fz="xs">
                            {" "}
                            ({person.owns} own)
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td ta="end" ff="monospace" fz="xs">
                        ${person.spend_usd.toFixed(2)}
                      </Table.Td>
                      <Table.Td>
                        <Menu position="bottom-end" withinPortal>
                          <Menu.Target>
                            <ActionIcon
                              size="sm"
                              variant="subtle"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <IconDots size={14} />
                            </ActionIcon>
                          </Menu.Target>
                          <Menu.Dropdown>
                            <Menu.Item onClick={() => setSelected(person.user_id)}>
                              Open
                            </Menu.Item>
                          </Menu.Dropdown>
                        </Menu>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
            <TablePagination state={paged} noun="people" />
            </>
          )}
        </Card>

        <div
          style={
            isCompact
              ? { width: "100%", flex: "none" }
              : { width: "26rem", flex: "none" }
          }
        >
          {selected ? (
            <PersonDetailPanel userId={selected} />
          ) : (
            !isCompact && (
              <Card padding="lg" radius="md" withBorder>
                <Text size="sm" c="dimmed">
                  Select someone to see their Hunts and act on their account.
                </Text>
              </Card>
            )
          )}
        </div>
      </Group>

      <ProvisionModal opened={provisionOpen} onClose={closeProvision} />
    </Stack>
  );
}
