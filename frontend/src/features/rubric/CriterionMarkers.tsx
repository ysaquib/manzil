// Quiet state markers for a rubric criterion: one tinted glyph each for "bonus"
// and "non-negotiable gate", explanation on hover (UI_DESIGN §4 — quiet status
// markers over badges; UI Decision Log 2026-07-25).
//
// These replace the former word-badges: at 30 cards a "non-negotiable" badge
// wrapped the title row and pushed the label out of the card.
import { ThemeIcon, Tooltip } from "@mantine/core";
import { IconShieldCheck, IconSparkles } from "@tabler/icons-react";

function Mark({
  label,
  color,
  children,
}: {
  label: string;
  color: string;
  children: React.ReactNode;
}) {
  return (
    // These marks exist only as a tooltip target, so on touch they have to open
    // on tap or they carry nothing at all.
    <Tooltip
      label={label}
      openDelay={200}
      maw={280}
      multiline
      events={{ hover: true, focus: true, touch: true }}
    >
      <ThemeIcon variant="transparent" color={color} size="sm" role="img" aria-label={label}>
        {children}
      </ThemeIcon>
    </Tooltip>
  );
}

export function BonusMark() {
  return (
    <Mark label="Bonus criterion — every delta is zero or positive" color="green">
      <IconSparkles size={15} stroke={1.5} />
    </Mark>
  );
}

export function GateMark({ setScore }: { setScore: number }) {
  return (
    <Mark
      label={`Non-negotiable — if this isn't met the listing's score is set to ${setScore}`}
      color="red"
    >
      <IconShieldCheck size={15} stroke={1.5} />
    </Mark>
  );
}
