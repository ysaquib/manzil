// Whitespace-grouped section — prefer over Divider (frontend/AGENTS.md).
import { Stack, Title } from "@mantine/core";
import type { ReactNode } from "react";

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap="xs">
      <Title order={5}>{title}</Title>
      {children}
    </Stack>
  );
}
