// Header toggle: explicit light/dark persisted via Mantine's color-scheme manager.
// Uses useComputedColorScheme so toggling works when the stored value is "auto".
import {
  ActionIcon,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";

export function ColorSchemeToggle({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("light");
  const isDark = computed === "dark";

  const toggle = () => setColorScheme(isDark ? "light" : "dark");

  return (
    <Tooltip label={isDark ? "Light mode" : "Dark mode"}>
      <ActionIcon
        variant="subtle"
        color="gray"
        size={size}
        onClick={toggle}
        aria-label="Toggle color scheme"
      >
        {isDark ? <IconSun size={18} stroke={1.5} /> : <IconMoon size={18} stroke={1.5} />}
      </ActionIcon>
    </Tooltip>
  );
}
