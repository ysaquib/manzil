// App entry (Phase 1 plan §5.2): MantineProvider + QueryClientProvider +
// AuthProvider + RouterProvider.
import "@fontsource-variable/literata";
import "@fontsource-variable/source-sans-3";
// Figures and code (UI_DESIGN §1). Weights 400/500 only — the mono is used for
// numerals, never for running text.
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";

import { localStorageColorSchemeManager, MantineProvider } from "@mantine/core";
import "@mantine/core/styles.css";
import "@mantine/carousel/styles.css";
import "@mantine/dates/styles.css";
import { Notifications } from "@mantine/notifications";
import "@mantine/notifications/styles.css";
import { QueryClientProvider } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { AuthProvider } from "./auth/AuthProvider";
import { COLOR_SCHEME_STORAGE_KEY } from "./lib/colorScheme";
import { createOfflinePersister, installMutationDefaults, persistOptions } from "./lib/offline";
import { queryClient } from "./lib/queryClient";
import { router } from "./routes/router";
import { cssVariablesResolver, theme } from "./theme";

const colorSchemeManager = localStorageColorSchemeManager({
  key: COLOR_SCHEME_STORAGE_KEY,
});

// Must run before render: a queued answer write restored from storage looks up
// its function by mutation key, and one restored before the default is
// registered never replays (VC-6).
installMutationDefaults(queryClient);
const persister = createOfflinePersister();

// Where persistence is unavailable the app still runs — it is simply online-only.
function Query({ children }: { children: React.ReactNode }) {
  return persister ? (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={persistOptions(persister)}
      // Restoring the queue is only half of it. A write rebuilt from storage
      // comes back paused and stays that way — the reconnect that would have
      // resumed it happened in a previous page — so the restore has to hand it
      // the nudge. Without this an answer taken offline survives the reload and
      // then sits there forever, which looks exactly like data loss.
      onSuccess={() => queryClient.resumePausedMutations()}
    >
      {children}
    </PersistQueryClientProvider>
  ) : (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider
      theme={theme}
      cssVariablesResolver={cssVariablesResolver}
      defaultColorScheme="auto"
      colorSchemeManager={colorSchemeManager}
    >
      <Notifications />
      <Query>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </Query>
    </MantineProvider>
  </React.StrictMode>,
);
