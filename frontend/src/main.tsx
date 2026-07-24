// App entry (Phase 1 plan §5.2): MantineProvider + QueryClientProvider +
// AuthProvider + RouterProvider.
import "@fontsource-variable/literata";
import "@fontsource-variable/source-sans-3";

import { localStorageColorSchemeManager, MantineProvider } from "@mantine/core";
import "@mantine/core/styles.css";
import "@mantine/carousel/styles.css";
import "@mantine/dates/styles.css";
import { Notifications } from "@mantine/notifications";
import "@mantine/notifications/styles.css";
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { AuthProvider } from "./auth/AuthProvider";
import { COLOR_SCHEME_STORAGE_KEY } from "./lib/colorScheme";
import { queryClient } from "./lib/queryClient";
import { router } from "./routes/router";
import { cssVariablesResolver, theme } from "./theme";

const colorSchemeManager = localStorageColorSchemeManager({
  key: COLOR_SCHEME_STORAGE_KEY,
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider
      theme={theme}
      cssVariablesResolver={cssVariablesResolver}
      defaultColorScheme="auto"
      colorSchemeManager={colorSchemeManager}
    >
      <Notifications />
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
