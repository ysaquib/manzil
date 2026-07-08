// Hunt switcher / landing (Phase 1 plan P1-9). Scaffold: lists the user's hunts
// and offers create; full styling + empty-state polish land with P1-9.
import { Button, Card, Container, Group, Stack, Text, TextInput, Title } from "@mantine/core";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useCreateHunt, useHunts } from "./api";

export function HuntSwitcherPage() {
  const { data: hunts, isLoading } = useHunts();
  const createHunt = useCreateHunt();
  const [name, setName] = useState("");

  return (
    <Container size="sm" py="xl">
      <Stack>
        <Title order={2}>Your hunts</Title>
        {isLoading && <Text>Loading…</Text>}
        {hunts?.map((hunt) => (
          <Card key={hunt.id} withBorder component={Link} to={`/h/${hunt.id}`}>
            <Text fw={500}>{hunt.name}</Text>
          </Card>
        ))}
        <Group>
          <TextInput
            placeholder="New hunt name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button
            onClick={() => createHunt.mutate({ name }, { onSuccess: () => setName("") })}
            disabled={!name || createHunt.isPending}
          >
            Create
          </Button>
        </Group>
      </Stack>
    </Container>
  );
}
