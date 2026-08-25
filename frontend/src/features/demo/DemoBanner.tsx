// The standing reminder that nothing here is saved (DM-7, DESIGN §16).
//
// Deliberately a persistent bar rather than a toast on first load. A visitor
// arriving at a demo will click something within seconds, and the one thing they
// must never wonder is whether they just changed somebody's real data. A message
// that has already faded cannot answer that.
//
// Tone matters as much as placement: this is an explanation, not a warning. The
// app is working exactly as intended, so the bar is quiet — clay, the
// established "the app is waiting on you / this is informational" hue — never
// red, which would read as an error the visitor caused.
import { Anchor, Group, Text } from "@mantine/core";
import { IconEye } from "@tabler/icons-react";

import { exitDemo, resetDemo } from "../../lib/demo";
import { useDemoRelease } from "./api";
import classes from "./DemoBanner.module.css";

export function DemoBanner() {
  // Mount the protected-release sentinel on every Hunt route, not only the
  // Overview and Map pages that need release data for their own rendering.
  useDemoRelease();
  return (
    <div className={classes.bar} role="status">
      <Group gap="xs" wrap="nowrap" justify="center">
        <IconEye size={15} aria-hidden />
        <Text size="sm" span fw={700}>
          Demo
        </Text>
        <Text size="sm" span className={classes.detail}>
          — you're exploring a real apartment hunt. Change anything you like; nothing is
          saved, and a reload puts it all back.
        </Text>
        <Anchor component="button" type="button" size="sm" onClick={resetDemo}>
          Reset
        </Anchor>
        <Anchor component="button" type="button" size="sm" onClick={exitDemo}>
          Leave
        </Anchor>
      </Group>
    </div>
  );
}
