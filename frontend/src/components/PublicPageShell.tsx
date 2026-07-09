// Shared chrome for login and hunt switcher — full viewport, wordmark, scheme toggle.
import { Box, Container, Group, Title } from "@mantine/core";
import type { ReactNode } from "react";

import { ColorSchemeToggle } from "./ColorSchemeToggle";

export function PublicPageShell({
  children,
  containerSize = "xs",
}: {
  children: ReactNode;
  containerSize?: "xs" | "sm" | "md";
}) {
  return (
    <Box mih="100dvh" bg="var(--mantine-color-body)">
      <Group justify="space-between" px="md" py="sm">
        <Title order={4}>Manzil</Title>
        <ColorSchemeToggle />
      </Group>
      <Container size={containerSize} py="xl">
        {children}
      </Container>
    </Box>
  );
}
