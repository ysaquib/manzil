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
} from "@mantine/core";
import { IconChevronRight, IconShieldLock } from "@tabler/icons-react";
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

  const empty = !isLoading && !error && (hunts ?? []).length === 0;

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

          {(hunts ?? []).map((hunt) => (
            <NavLink
              key={hunt.id}
              component={Link}
              to={`/h/${hunt.id}`}
              label={hunt.name}
              description={`Created ${huntCreatedDate(hunt.created_at)}`}
              p="sm"
              style={{
                border: "1px solid var(--mantine-color-default-border)",
                borderRadius: "var(--mantine-radius-md)",
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
