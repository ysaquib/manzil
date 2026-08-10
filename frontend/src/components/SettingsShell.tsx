// Shared settings frame (P3-16, DESIGN §20 v3.27) — used twice: hunt-scoped at
// /h/:huntId/settings and account-scoped at /account. A tab rail beside a
// bounded content column, plus one save bar per panel that appears only when
// that panel is dirty.
//
// The rail's second line is load-bearing: two or three tabs alone read as thin,
// and the subtitle is what lets someone find the color picker without opening
// every tab. Below `sm` the rail becomes a horizontal scroller above the
// column (frontend/AGENTS.md responsive rule).
import { Box, Button, Group, Paper, Stack, Text, UnstyledButton } from "@mantine/core";
import type { ReactNode } from "react";

import classes from "./SettingsShell.module.css";

export interface SettingsTab {
  /** URL segment for this tab — `/h/:id/settings/<value>` or `/account/<value>`. */
  value: string;
  label: string;
  /** The second rail line: what lives in here, before you click. */
  description?: string;
  icon: ReactNode;
  /** Marks a designed-but-unshipped tab. */
  pending?: boolean;
}

export function SettingsShell({
  tabs,
  active,
  onSelect,
  children,
}: {
  tabs: SettingsTab[];
  active: string;
  onSelect: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <Box className={classes.shell}>
      <Box className={classes.railScroll}>
        <Stack gap={2} className={classes.rail} role="tablist" aria-label="Settings sections">
          {tabs.map((tab) => {
            const selected = tab.value === active;
            return (
              <UnstyledButton
                key={tab.value}
                role="tab"
                aria-selected={selected}
                data-active={selected || undefined}
                className={classes.railItem}
                onClick={() => onSelect(tab.value)}
              >
                <span className={classes.railIcon}>{tab.icon}</span>
                <span className={classes.railText}>
                  <Text size="sm" fw={selected ? 600 : 500} lh={1.3}>
                    {tab.label}
                  </Text>
                  {tab.description && (
                    <Text size="xs" c="dimmed" lh={1.3} className={classes.railDescription}>
                      {tab.description}
                    </Text>
                  )}
                </span>
                {tab.pending && <span className={classes.pendingDot} aria-hidden />}
              </UnstyledButton>
            );
          })}
        </Stack>
      </Box>

      <Stack gap="md" className={classes.column}>
        {children}
      </Stack>
    </Box>
  );
}

/**
 * Sticky footer for one panel's batched edits. Rendered only when something is
 * dirty, and it names what changed — "unsaved changes" alone leaves the reader
 * hunting for which field they touched.
 */
export function SettingsSaveBar({
  dirtyLabels,
  onSave,
  onDiscard,
  saving = false,
}: {
  dirtyLabels: string[];
  onSave: () => void;
  onDiscard: () => void;
  saving?: boolean;
}) {
  if (dirtyLabels.length === 0) return null;
  const count = dirtyLabels.length;
  return (
    <Paper className={classes.saveBar} withBorder role="status">
      <Group gap="sm" wrap="nowrap" justify="space-between">
        <Text size="sm" className={classes.saveMessage}>
          <Text span fw={600} c="primary">
            {count} unsaved {count === 1 ? "change" : "changes"}
          </Text>{" "}
          — {dirtyLabels.join(", ")}
        </Text>
        <Group gap="xs" wrap="nowrap">
          <Button variant="subtle" color="gray" size="xs" onClick={onDiscard} disabled={saving}>
            Discard
          </Button>
          <Button size="xs" onClick={onSave} loading={saving}>
            Save changes
          </Button>
        </Group>
      </Group>
    </Paper>
  );
}
