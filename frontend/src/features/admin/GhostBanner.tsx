// The ghost-view banner (AD-4, DESIGN §4.2).
//
// Not decoration. Without a persistent marker, an admin two clicks deep into
// somebody else's Hunt cannot tell whose data they are editing, and the first
// destructive mistake will be exactly that. It stays on every screen of the
// Hunt for the same reason — a banner that only appears on entry is a banner
// you have already forgotten by the time it matters.
import { Anchor, Group, Text } from "@mantine/core";
import { IconEyeglass } from "@tabler/icons-react";
import { Link } from "react-router-dom";

import classes from "./GhostBanner.module.css";

export function GhostBanner({ huntName }: { huntName?: string | null }) {
  return (
    <div className={classes.banner} role="status">
      <Group gap="xs" wrap="nowrap" justify="center">
        <IconEyeglass size={16} stroke={1.6} />
        <Text size="sm" fw={600}>
          Viewing as admin
        </Text>
        <Text size="sm" className={classes.detail}>
          {huntName ? `You are not a member of ${huntName}.` : "You are not a member of this Hunt."}{" "}
          Changes you make are recorded against your account.
        </Text>
        <Anchor component={Link} to="/admin/hunts" size="sm" className={classes.exit}>
          Back to admin
        </Anchor>
      </Group>
    </div>
  );
}
