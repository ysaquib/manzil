// Interest status as a coloured chip that opens the status menu, plus the
// labelled "Visited" marker (UI Decision Log 2026-07-26).
//
// This replaces a 140px `Select` and a bare `Checkbox` in every row — a lot of
// permanent form chrome for a value that changes occasionally. The chip shows
// the state at rest and becomes the control on click; visited says the word
// rather than leaving an unlabelled tick to be guessed at.
import { Badge, Box, Group, Menu, Tooltip, UnstyledButton } from "@mantine/core";
import { IconCheck, IconChevronDown } from "@tabler/icons-react";

import { interestLabel, interestTone } from "./interestStatus";
import { INTEREST_STATUSES, type InterestStatus } from "./types";

/** Keeps badge triggers on one line box so adjacent chips align in table cells. */
const CHIP_TRIGGER_STYLES = {
  root: {
    display: "inline-flex",
    alignItems: "center",
    lineHeight: 1,
  },
} as const;

const CHIP_BADGE_STYLES = {
  root: {
    display: "inline-flex",
    alignItems: "center",
  },
} as const;

const CHIP_SLOT_STYLE = {
  display: "inline-flex",
  alignItems: "center",
  lineHeight: 1,
} as const;

export function StatusChip({
  status,
  disabled = false,
  onChange,
}: {
  status: InterestStatus | null;
  disabled?: boolean;
  onChange: (next: InterestStatus | null) => void;
}) {
  const label = interestLabel(status);
  return (
    <Menu position="bottom-start" withinPortal disabled={disabled}>
      <Menu.Target>
        <UnstyledButton
          aria-label={`interest status: ${label}`}
          disabled={disabled}
          styles={CHIP_TRIGGER_STYLES}
        >
          <Badge
            variant={status === null ? "outline" : "light"}
            color={status === null ? "var(--mantine-color-dimmed)" : interestTone(status)}
            rightSection={!disabled && <IconChevronDown size={11} stroke={2} />}
            styles={{
              root: {
                ...CHIP_BADGE_STYLES.root,
                ...(status === null ? { borderStyle: "dashed" as const } : null),
              },
            }}
          >
            {label}
          </Badge>
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item onClick={() => onChange(null)}>Undecided</Menu.Item>
        {INTEREST_STATUSES.map((option) => (
          <Menu.Item key={option} onClick={() => onChange(option)}>
            {interestLabel(option)}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

export function VisitedToggle({
  visited,
  disabled = false,
  onChange,
}: {
  visited: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  if (!visited) {
    return (
      <Tooltip label="Mark visited" openDelay={300}>
        <UnstyledButton
          aria-label="mark visited"
          disabled={disabled}
          onClick={() => onChange(true)}
          styles={CHIP_TRIGGER_STYLES}
        >
          <Badge
            variant="outline"
            color="var(--mantine-color-dimmed)"
            c="dimmed"
            style={{ borderStyle: "dashed"}}
            // leftSection={<IconCircleDotted size={11} />}
            styles={CHIP_BADGE_STYLES}
          >
            Not Visited
          </Badge>
        </UnstyledButton>
      </Tooltip>
    );
  }
  return (
    <Tooltip label="Visited — click to clear" openDelay={300}>
      <UnstyledButton
        aria-label="visited"
        disabled={disabled}
        onClick={() => onChange(false)}
        styles={CHIP_TRIGGER_STYLES}
      >
        <Badge
          variant="light"
          color="green"
          leftSection={<IconCheck size={11} stroke={2} />}
          styles={CHIP_BADGE_STYLES}
        >
          Visited
        </Badge>
      </UnstyledButton>
    </Tooltip>
  );
}

/** Status + visited as one cell, so curation reads as a single unit. */
export function CurationCell(props: {
  status: InterestStatus | null;
  visited: boolean;
  disabled?: boolean;
  onStatus: (next: InterestStatus | null) => void;
  onVisited: (next: boolean) => void;
}) {
  return (
    <Group gap={6} wrap="nowrap" align="center">
      <Box style={CHIP_SLOT_STYLE}>
        <StatusChip status={props.status} disabled={props.disabled} onChange={props.onStatus} />
      </Box>
      <Box style={CHIP_SLOT_STYLE}>
        <VisitedToggle
          visited={props.visited}
          disabled={props.disabled}
          onChange={props.onVisited}
        />
      </Box>
    </Group>
  );
}
