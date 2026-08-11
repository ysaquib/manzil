import { Alert, Text } from "@mantine/core";
import { IconArchive, IconLock } from "@tabler/icons-react";

import type { HuntReadOnlyReason } from "./access";

export function HuntStateBanner({
  reason,
  adminOverride = false,
}: {
  reason: HuntReadOnlyReason;
  adminOverride?: boolean;
}) {
  if (!reason) return null;
  const locked = reason === "locked";
  return (
    <Alert
      mb="md"
      color={locked ? "orange" : "gray"}
      icon={locked ? <IconLock size={18} /> : <IconArchive size={18} />}
      title={locked ? "Hunt locked" : "Archived Hunt"}
    >
      <Text size="sm">
        {locked
          ? "A Site Admin locked this Hunt. Everyone can view it, but nobody can make changes until an admin unlocks it."
          : adminOverride
            ? "This Hunt is archived. Your Site Admin changes use the audited admin path; members remain read-only."
            : "This Hunt is preserved as read-only. Its Owner can restore or permanently delete it from Settings."}
      </Text>
    </Alert>
  );
}
