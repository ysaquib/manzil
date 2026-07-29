// Non-fatal run degradations on a task card (§10.8). Deliberately quieter than
// `job.error`: amber, not red, and phrased as what the run couldn't do rather
// than as a failure — the job kept going and its result is still usable.
import { Group, Text } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

import type { JobWarning } from "./api";

export function JobWarnings({ warnings }: { warnings: JobWarning[] | undefined }) {
  if (!warnings?.length) return null;
  return (
    <>
      {warnings.map((warning) => (
        <Group key={`${warning.stage}:${warning.code}`} gap={6} wrap="nowrap" align="flex-start">
          <IconAlertTriangle
            size={13}
            color="var(--mantine-color-yellow-6)"
            style={{ flexShrink: 0, marginTop: 2 }}
            aria-hidden
          />
          <Text size="xs" c="yellow.7">
            {warning.message}
          </Text>
        </Group>
      ))}
    </>
  );
}
