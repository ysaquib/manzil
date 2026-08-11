// Hunt switcher / landing (P1-9): the user's hunts + create. Empty state
// leads with the create form — the first-run path is "make a hunt".
import {
  Button,
  Group,
  Loader,
  NavLink,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from "@mantine/core";
import { IconArchive, IconChevronDown, IconChevronRight, IconLock, IconShieldLock } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PublicPageShell } from "../../components/PublicPageShell";
import { UserMenu } from "../../components/UserMenu";
import { useAdminIdentity } from "../admin/api";
import { ApiError } from "../../lib/apiClient";
import { useCreateHunt, useHunts } from "./api";

const huntCreatedDate = (createdAt: string) => {
  const parts = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).formatToParts(new Date(createdAt));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((candidate) => candidate.type === type)?.value ?? "";
  return `${part("weekday")}, ${part("day")} ${part("month")}, ${part("year")}`;
};

export function HuntSwitcherPage() {
  const { data: hunts, isLoading, error } = useHunts();
  const admin = useAdminIdentity();
  const createHunt = useCreateHunt();
  const [name, setName] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const activeHunts = (hunts ?? []).filter((hunt) => !hunt.archived_at);
  const archivedHunts = (hunts ?? []).filter((hunt) => Boolean(hunt.archived_at));

  const create = () =>
    createHunt.mutate(
      { name: name.trim(), domain: "rent" },
      {
        onSuccess: () => setName(""),
        onError: (e) =>
          notifications.show({
            title: "Couldn't create hunt",
            message: e instanceof ApiError ? e.message : "Unexpected error",
            color: "red",
          }),
      },
    );

  const empty = !isLoading && !error && activeHunts.length === 0 && archivedHunts.length === 0;

  return (
    <PublicPageShell rightSlot={<UserMenu />}>
      <Stack gap="lg">
        <div>
          <Text fw={600} size="lg">
            {empty ? "Start your first hunt" : "Your hunts"}
          </Text>
          <Text c="dimmed" size="sm">
            {empty
              ? "Every search starts somewhere — give this one a name."
              : "Pick up where you left off, or start fresh."}
          </Text>
        </div>

        {isLoading && (
          <Group justify="center" py="lg">
            <Loader />
          </Group>
        )}
        {error && (
          <Text c="red" size="sm">
            Couldn't load hunts: {error.message}
          </Text>
        )}

        <Stack gap="sm">
          {admin.data?.is_site_admin && (
            <NavLink
              component={Link}
              to="/admin"
              label="Admin panel"
              description="Manage Manzil"
              leftSection={<IconShieldLock size={18} stroke={1.6} />}
              rightSection={<IconChevronRight size={16} stroke={1.5} />}
              active
              variant="filled"
              p="sm"
              style={{ borderRadius: "var(--mantine-radius-md)" }}
            />
          )}

          {activeHunts.map((hunt) => (
            <NavLink
              key={hunt.id}
              component={Link}
              to={`/h/${hunt.id}`}
              label={hunt.name}
              description={
                hunt.locked_at
                  ? `Locked · Created ${huntCreatedDate(hunt.created_at)}`
                  : `Created ${huntCreatedDate(hunt.created_at)}`
              }
              leftSection={hunt.locked_at ? <IconLock size={17} stroke={1.5} /> : undefined}
              p="sm"
              style={{
                border: "1px solid var(--mantine-color-default-border)",
                borderRadius: "var(--mantine-radius-md)",
              }}
              rightSection={<IconChevronRight size={16} stroke={1.5} color="var(--mantine-color-dimmed)" />}
            />
          ))}

          {archivedHunts.length > 0 && (
            <UnstyledButton
              onClick={() => setShowArchived((value) => !value)}
              aria-expanded={showArchived}
              c="dimmed"
              px="xs"
              py={6}
              style={{ alignSelf: "flex-start", borderRadius: "var(--mantine-radius-sm)" }}
            >
              <Group gap={6} wrap="nowrap">
                <IconArchive size={15} stroke={1.5} />
                <Text size="xs" fw={500}>
                  {showArchived ? "Hide" : "Show"} archived ({archivedHunts.length})
                </Text>
                <IconChevronDown
                  size={13}
                  stroke={1.5}
                  style={{ transform: showArchived ? "rotate(180deg)" : undefined }}
                />
              </Group>
            </UnstyledButton>
          )}

          {showArchived &&
            archivedHunts.map((hunt) => (
              <NavLink
                key={hunt.id}
                component={Link}
                to={`/h/${hunt.id}`}
                label={hunt.name}
                description={`Archived · Created ${huntCreatedDate(hunt.created_at)}`}
                leftSection={<IconArchive size={17} stroke={1.5} />}
                p="sm"
                style={{
                  border: "1px solid var(--mantine-color-default-border)",
                  borderRadius: "var(--mantine-radius-md)",
                  opacity: 0.82,
                }}
                rightSection={<IconChevronRight size={16} stroke={1.5} color="var(--mantine-color-dimmed)" />}
              />
            ))}
        </Stack>

        <Group align="flex-end" gap="sm">
          <TextInput
            label={empty ? "Hunt name" : "New hunt"}
            placeholder="e.g. Apartment Search 2026"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && create()}
            style={{ flex: 1 }}
          />
          <Button onClick={create} disabled={!name.trim() || createHunt.isPending}>
            Create
          </Button>
        </Group>
      </Stack>
    </PublicPageShell>
  );
}
