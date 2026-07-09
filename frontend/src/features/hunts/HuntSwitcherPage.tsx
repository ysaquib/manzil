// Hunt switcher / landing (P1-9): the user's hunts + create. Empty state
// leads with the create form — the first-run path is "make a hunt".
import {
  Button,
  Card,
  Container,
  Group,
  Loader,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../lib/apiClient";
import { useCreateHunt, useHunts } from "./api";

export function HuntSwitcherPage() {
  const { data: hunts, isLoading, error } = useHunts();
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
    <Container size="xs" py="xl">
      <Stack gap="lg">
        <div>
          <Title order={2}>Manzil</Title>
          <Text c="dimmed" size="sm">
            {empty ? "Name your first hunt to get started." : "Pick a hunt or start a new one."}
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

        {(hunts ?? []).map((hunt) => (
          <Card key={hunt.id} component={Link} to={`/h/${hunt.id}`} padding="md">
            <Group justify="space-between">
              <Text fw={600}>{hunt.name}</Text>
              <Text size="xs" c="dimmed">
                rubric v{hunt.rubric_version}
              </Text>
            </Group>
          </Card>
        ))}

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
    </Container>
  );
}
