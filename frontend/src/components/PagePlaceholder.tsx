// Scaffold placeholder — a route renders this until its P1 feature task fills
// in. Keeps the app navigable end-to-end today without faking data.
import { Alert, Stack, Title } from "@mantine/core";

export function PagePlaceholder({ title, task }: { title: string; task: string }) {
  return (
    <Stack>
      <Title order={2}>{title}</Title>
      <Alert color="gray" title="Scaffolded">
        This view lands with {task}.
      </Alert>
    </Stack>
  );
}
