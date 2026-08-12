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
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
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
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconDots, IconSearch, IconTrash, IconUserPlus } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  ConfirmDeleteModal,
  type DeletionTarget,
} from "../../components/ConfirmDeleteModal";
import { TablePagination, usePagedRows } from "../../components/TablePagination";
import { ApiError } from "../../lib/apiClient";
import { HuntPicker } from "./HuntPicker";
import {
  useAdminPeople,
  useAdminPerson,
  useDeletePerson,
  useProvisionPerson,
  usePersonAction,
  useRemoveMembership,
  useSetMembership,
  type PersonDetail,
  type PersonRow,
} from "./api";
import {
  ADMIN_SEARCH_MODE_OPTIONS,
  adminDirectoryLink,
  adminSearchMode,
} from "./navigation";

/** Accounts are the noun everywhere in this panel — never "user" in copy. */
const ACCOUNT_NOUN = { singular: "account", plural: "accounts" };

/** The typed confirmation is the email: display names repeat, addresses do not. */
function personLabel(person: Pick<PersonRow, "email" | "display_name" | "user_id">): string {
  return person.email ?? person.display_name ?? person.user_id;
}

/** Why the API would refuse this delete, phrased as the operator's next step. */
function blockingReason(person: Pick<PersonRow, "owns">): string | undefined {
  if (person.owns === 0) return undefined;
  return `owns ${person.owns} Hunt${person.owns === 1 ? "" : "s"} — transfer ownership first`;
}

function personTarget(person: PersonRow): DeletionTarget {
  return {
    id: person.user_id,
    label: personLabel(person),
    description: person.display_name ?? undefined,
    blockedReason: blockingReason(person),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unexpected error";
}

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

function PersonDetailPanel({
  userId,
  onDeleted,
}: {
  userId: string;
  onDeleted: (userId: string) => void;
}) {
  const person = useAdminPerson(userId);
  const action = usePersonAction();
  const setMembership = useSetMembership();
  const removeMembership = useRemoveMembership();
  const deletePerson = useDeletePerson();
  const [addHunt, setAddHunt] = useState<string | null>(null);
  const [addRole, setAddRole] = useState<string>("member");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRemoval, setConfirmRemoval] = useState<PersonDetail["memberships"][number] | null>(
    null,
  );

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
              onClick={() => setConfirmDelete(true)}
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
          <Stack gap="xs">
            {p.memberships.map((m) => (
              <Card
                key={m.hunt_id}
                component="article"
                aria-label={`${m.hunt_name} membership`}
                padding="xs"
                radius="sm"
                withBorder
              >
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Anchor component={Link} to={adminDirectoryLink("hunts", m.hunt_id)} fw={600}>
                      {m.hunt_name}
                    </Anchor>
                    <Text size="xs" c="dimmed" ff="monospace" truncate>
                      {m.hunt_id}
                    </Text>
                    {m.joined_at && (
                      <Text size="xs" c="dimmed">
                        Joined {new Date(m.joined_at).toLocaleDateString()}
                      </Text>
                    )}
                  </div>
                  <Stack gap={4} align="flex-end">
                    <Badge size="sm" variant="light" color={m.role === "owner" ? "primary" : "gray"}>
                      {m.role}
                    </Badge>
                    <Group gap={4} wrap="nowrap">
                      <Select
                        size="xs"
                        w={112}
                        aria-label={`Role in ${m.hunt_name}`}
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
                          aria-label={`Remove from ${m.hunt_name}`}
                          disabled={m.role === "owner"}
                          onClick={() => setConfirmRemoval(m)}
                        >
                          ×
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Stack>
                </Group>
              </Card>
            ))}
          </Stack>
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

      <ConfirmDeleteModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        noun={ACCOUNT_NOUN}
        loading={deletePerson.isPending}
        targets={[
          {
            id: p.user_id,
            label: personLabel(p),
            description: p.display_name ?? undefined,
          },
        ]}
        warning="The account is removed from Supabase Auth and cannot be signed into again. Suspension is the reversible alternative."
        onConfirm={() =>
          deletePerson.mutate(userId, {
            onSuccess: () => {
              setConfirmDelete(false);
              onDeleted(userId);
              notifications.show({
                message: `${personLabel(p)} deleted.`,
                color: "green",
              });
            },
            onError: (error) =>
              notifications.show({
                title: "Couldn't delete the account",
                message: errorMessage(error),
                color: "red",
              }),
          })
        }
      >
        <Text size="sm" c="dimmed">
          {p.memberships.length === 0
            ? "They are not a member of any Hunt."
            : `They will be removed from ${p.memberships.length} Hunt${
                p.memberships.length === 1 ? "" : "s"
              }. ${p.feedback_count} filed report${
                p.feedback_count === 1 ? "" : "s"
              } stay recorded.`}
        </Text>
      </ConfirmDeleteModal>

      {/* Reversible — the Hunt picker below re-adds them — so this one shows the
          subject and asks for a click, not a typed name. */}
      <ConfirmDeleteModal
        opened={confirmRemoval !== null}
        onClose={() => setConfirmRemoval(null)}
        noun={{ singular: "membership", plural: "memberships" }}
        title="Remove from this Hunt?"
        confirmLabel="Remove"
        requireTypedConfirmation={false}
        loading={removeMembership.isPending}
        warning="They lose access to this Hunt immediately. Their comments, ratings and Visits stay with the Hunt, and you can add them back below."
        targets={
          confirmRemoval
            ? [
                {
                  id: confirmRemoval.hunt_id,
                  label: confirmRemoval.hunt_name,
                  description: `${personLabel(p)} · ${confirmRemoval.role}`,
                },
              ]
            : []
        }
        onConfirm={() => {
          if (!confirmRemoval) return;
          removeMembership.mutate(
            { userId, huntId: confirmRemoval.hunt_id },
            {
              onSuccess: () => setConfirmRemoval(null),
              onError: (error) =>
                notifications.show({
                  title: "Couldn't remove them from the Hunt",
                  message: errorMessage(error),
                  color: "red",
                }),
            },
          );
        }}
      />
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
  const [searchParams] = useSearchParams();
  const requestedSearch = searchParams.get("search") ?? "";
  const requestedMode = adminSearchMode(searchParams.get("search_mode"));
  const requestedSelected = searchParams.get("selected");
  const [search, setSearch] = useState(requestedSearch);
  const [searchMode, setSearchMode] = useState(requestedMode);
  const [selected, setSelected] = useState<string | null>(requestedSelected);
  const [provisionOpen, { open: openProvision, close: closeProvision }] = useDisclosure(false);
  const people = useAdminPeople(search, searchMode);
  // Phone width: the roster and the detail panel cannot sit side by side in
  // 24rem, so the panel moves under the list and only appears once someone is
  // picked. The placeholder card ("select someone") is desktop-only furniture.
  const isCompact = useMediaQuery("(max-width: 48em)") ?? false;
  const paged = usePagedRows(people.data ?? [], "admin-people");

  // Bulk deletion (checked rows) is deliberately separate from `selected`, the
  // one row whose detail panel is open: an operator ticking five accounts to
  // delete is not asking to read the fifth one's memberships.
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const deletePerson = useDeletePerson();

  useEffect(() => {
    setSearch(requestedSearch);
    setSearchMode(requestedMode);
    setSelected(requestedSelected);
  }, [requestedMode, requestedSearch, requestedSelected]);

  const rows = people.data ?? [];
  const checkedRows = rows.filter((person) => checked.has(person.user_id));
  const toggleRow = (userId: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  // Select-all is the header checkbox above *this page* of rows, so it means
  // this page — never a silent selection of a roster nobody has scrolled.
  const pageIds = paged.items.map((person) => person.user_id);
  const allOnPageChecked = pageIds.length > 0 && pageIds.every((id) => checked.has(id));
  const toggleAllOnPage = () =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (allOnPageChecked) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });

  // Sequential, not parallel: every one of these is an audited account deletion
  // and a partial failure has to name the accounts that survived.
  const deleteChecked = async (targets: DeletionTarget[]) => {
    setBulkBusy(true);
    const failed: { target: DeletionTarget; reason: string }[] = [];
    const deletedIds: string[] = [];
    for (const target of targets) {
      try {
        await deletePerson.mutateAsync(target.id);
        deletedIds.push(target.id);
      } catch (error) {
        failed.push({ target, reason: errorMessage(error) });
      }
    }
    setBulkBusy(false);
    setBulkOpen(false);
    // What survived stays ticked: the operator's next move is on those rows,
    // and a cleared selection would hide which ones were refused.
    setChecked(new Set(failed.map((entry) => entry.target.id)));
    if (selected && deletedIds.includes(selected)) setSelected(null);
    notifications.show({
      color: failed.length === 0 ? "green" : "red",
      title: `${deletedIds.length} of ${targets.length} account${
        targets.length === 1 ? "" : "s"
      } deleted`,
      message:
        failed.length === 0
          ? "The selection is cleared."
          : `Refused: ${failed
              .map((entry) => `${entry.target.label} (${entry.reason})`)
              .join("; ")}`,
    });
  };

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
          <Select
            size="xs"
            aria-label="People search mode"
            data={ADMIN_SEARCH_MODE_OPTIONS}
            value={searchMode}
            allowDeselect={false}
            onChange={(value) => value && setSearchMode(value as typeof searchMode)}
            w={isCompact ? 132 : 140}
          />
          <TextInput
            size="xs"
            placeholder={searchMode === "id" ? "Account ID…" : "Search name or email…"}
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
          {checked.size > 0 && (
            <Group
              p="xs"
              gap="xs"
              justify="space-between"
              wrap="wrap"
              bg="var(--mantine-color-default-hover)"
            >
              <Text size="sm" fw={600}>
                {checked.size} selected
              </Text>
              <Group gap="xs">
                <Button size="xs" variant="default" onClick={() => setChecked(new Set())}>
                  Clear
                </Button>
                <Button
                  size="xs"
                  color="red"
                  variant="light"
                  leftSection={<IconTrash size={14} />}
                  onClick={() => setBulkOpen(true)}
                >
                  Delete {checked.size} account{checked.size === 1 ? "" : "s"}
                </Button>
              </Group>
            </Group>
          )}
          {people.data && people.data.length > 0 && (
            <>
            {isCompact ? (
              <Stack gap="xs" p="xs">
                <Checkbox
                  size="xs"
                  label="Select every account on this page"
                  checked={allOnPageChecked}
                  indeterminate={!allOnPageChecked && pageIds.some((id) => checked.has(id))}
                  onChange={toggleAllOnPage}
                />
                {paged.items.map((person) => (
                  <Card
                    key={person.user_id}
                    padding="sm"
                    radius="sm"
                    withBorder
                    onClick={() => setSelected(person.user_id)}
                    bg={
                      selected === person.user_id
                        ? "var(--mantine-color-primary-light)"
                        : undefined
                    }
                    style={{ cursor: "pointer" }}
                  >
                    <Group align="flex-start" wrap="nowrap">
                      <Checkbox
                        size="xs"
                        mt={3}
                        aria-label={`Select ${personLabel(person)}`}
                        checked={checked.has(person.user_id)}
                        onChange={() => toggleRow(person.user_id)}
                        onClick={(event) => event.stopPropagation()}
                      />
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <Text size="sm" fw={600} truncate>
                          {person.display_name ?? "—"}
                        </Text>
                        <Text size="xs" c="dimmed" ff="monospace" truncate>
                          {person.email}
                        </Text>
                        <Group justify="space-between" mt="xs" align="flex-end">
                          <StateBadges person={person} />
                          <Text size="xs" ff="monospace" c="dimmed">
                            {person.hunts} Hunts · ${person.spend_usd.toFixed(2)}
                          </Text>
                        </Group>
                      </div>
                    </Group>
                  </Card>
                ))}
              </Stack>
            ) : (
            <Table.ScrollContainer minWidth={560}>
              <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={40}>
                      <Checkbox
                        size="xs"
                        aria-label="Select every account on this page"
                        checked={allOnPageChecked}
                        indeterminate={!allOnPageChecked && pageIds.some((id) => checked.has(id))}
                        onChange={toggleAllOnPage}
                      />
                    </Table.Th>
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
                      <Table.Td onClick={(event) => event.stopPropagation()}>
                        <Checkbox
                          size="xs"
                          aria-label={`Select ${personLabel(person)}`}
                          checked={checked.has(person.user_id)}
                          onChange={() => toggleRow(person.user_id)}
                        />
                      </Table.Td>
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
            )}
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
            <PersonDetailPanel
              userId={selected}
              onDeleted={(userId) => {
                setSelected(null);
                setChecked((prev) => {
                  const next = new Set(prev);
                  next.delete(userId);
                  return next;
                });
              }}
            />
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

      <ConfirmDeleteModal
        opened={bulkOpen}
        onClose={() => setBulkOpen(false)}
        noun={ACCOUNT_NOUN}
        targets={checkedRows.map(personTarget)}
        loading={bulkBusy}
        warning="Each account is removed from Supabase Auth and cannot be signed into again. Accounts that own a Hunt, or that created a Visit, are refused by the API and are skipped here."
        onConfirm={(targets) => void deleteChecked(targets)}
      />
    </Stack>
  );
}
