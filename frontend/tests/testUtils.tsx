// Shared component-test harness: Mantine + a fresh Query client per render so
// tests never share caches or hit retry/backoff.
import { localStorageColorSchemeManager, MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

import { COLOR_SCHEME_STORAGE_KEY } from "../src/lib/colorScheme";
import { theme } from "../src/theme";

const colorSchemeManager = localStorageColorSchemeManager({
  key: COLOR_SCHEME_STORAGE_KEY,
});

export function renderWithProviders(
  ui: ReactNode,
  options?: { colorScheme?: "light" | "dark" },
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MantineProvider
      theme={theme}
      defaultColorScheme="light"
      colorSchemeManager={colorSchemeManager}
      forceColorScheme={options?.colorScheme}
    >
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </MantineProvider>,
  );
}
