import {
  Badge,
  Box,
  Code,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
  UnstyledButton,
  useMantineTheme,
} from "@mantine/core";
import { useState } from "react";

import { PublicPageShell } from "../components/PublicPageShell";

function Palette({ name, shades }: { name: string; shades: readonly string[] }) {
  const defaultShade = Math.min(6, shades.length - 1);
  const [activeShade, setActiveShade] = useState(defaultShade);
  const activeColor = shades[activeShade];

  return (
    <Paper p="md" withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600}>{name}</Text>
          <Text c="dimmed" size="xs">
            {shades.length} shades
          </Text>
        </Group>

        <Box
          h={180}
          bg={activeColor}
          style={{
            borderRadius: "var(--mantine-radius-md)",
            border: "1px solid var(--mantine-color-default-border)",
          }}
        />
        <Group justify="space-between" gap="xs">
          <Text size="sm" fw={600}>
            Shade {activeShade}
          </Text>
          <Code fz="xs">{activeColor}</Code>
        </Group>

        <Box
          onMouseLeave={() => setActiveShade(defaultShade)}
          style={{ display: "grid", gridTemplateColumns: "repeat(10, minmax(0, 1fr))", gap: 4 }}
        >
          {shades.map((color, shade) => (
            <UnstyledButton
              key={`${name}-${shade}`}
              aria-label={`${name} shade ${shade}: ${color}`}
              title={`${shade} · ${color}`}
              onMouseEnter={() => setActiveShade(shade)}
              onFocus={() => setActiveShade(shade)}
              onBlur={() => setActiveShade(defaultShade)}
            >
              <Box
                h={30}
                bg={color}
                style={{
                  borderRadius: 4,
                  border:
                    shade === activeShade
                      ? "2px solid var(--mantine-color-text)"
                      : "1px solid var(--mantine-color-default-border)",
                }}
              />
              <Text size="xs" fw={shade === activeShade ? 700 : 500} ta="center" mt={2}>
                {shade}
              </Text>
            </UnstyledButton>
          ))}
        </Box>
      </Stack>
    </Paper>
  );
}

export function ColorsPage() {
  const theme = useMantineTheme();
  const palettes = Object.entries(theme.colors).sort(([left], [right]) =>
    left.localeCompare(right),
  );
  const primary = theme.colors[theme.primaryColor];
  const primaryShade =
    typeof theme.primaryShade === "number"
      ? `${theme.primaryShade}`
      : `light ${theme.primaryShade.light} · dark ${theme.primaryShade.dark}`;

  return (
    <PublicPageShell containerSize="md">
      <Stack gap="xl">
        <div>
          <Group gap="sm">
            <Title order={2}>Color lab</Title>
            <Badge color="gray">development only</Badge>
          </Group>
          <Text c="dimmed" mt={4}>
            The active Mantine theme palettes. Shade numbers and stored color values are shown below.
          </Text>
        </div>

        <section>
          <Group mb="sm" gap="sm">
            <Title order={3}>Primary color</Title>
            <Badge color={theme.primaryColor}>{theme.primaryColor}</Badge>
            <Text c="dimmed" size="sm">
              Primary shade: {primaryShade}
            </Text>
          </Group>
          <Palette name={theme.primaryColor} shades={primary} />
        </section>

        <section>
          <Title order={3} mb="sm">
            All Mantine colors
          </Title>
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            {palettes.map(([name, shades]) => (
              <Palette key={name} name={name} shades={shades} />
            ))}
          </SimpleGrid>
        </section>
      </Stack>
    </PublicPageShell>
  );
}
