// Interest status as a coloured chip that opens the status menu, plus the
// labelled "Visited" marker (UI Decision Log 2026-07-26).
//
// This replaces a 140px `Select` and a bare `Checkbox` in every row — a lot of
// permanent form chrome for a value that changes occasionally. The chip shows
// the state at rest and becomes the control on click; visited says the word
// rather than leaving an unlabelled tick to be guessed at.
import { Badge, Group, Menu, Tooltip, UnstyledButton } from "@mantine/core";
import { IconCheck, IconChevronDown } from "@tabler/icons-react";

import { interestLabel, interestTone } from "./interestStatus";
import { INTEREST_STATUSES, type InterestStatus } from "./types";

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
        <UnstyledButton aria-label={`interest status: ${label}`} disabled={disabled}>
          <Badge
            variant={status === null ? "outline" : "light"}
            color={status === null ? "gray" : interestTone(status)}
            rightSection={!disabled && <IconChevronDown size={11} stroke={2} />}
            styles={status === null ? { root: { borderStyle: "dashed" } } : undefined}
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
        >
          <Badge variant="outline" color="gray" c="dimmed" leftSection={<IconCheck size={11} />}>
            Visit
          </Badge>
        </UnstyledButton>
      </Tooltip>
    );
  }
  return (
    <Tooltip label="Visited — click to clear" openDelay={300}>
      <UnstyledButton aria-label="visited" disabled={disabled} onClick={() => onChange(false)}>
        <Badge variant="default" leftSection={<IconCheck size={11} stroke={2.5} />}>
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
    <Group gap={6} wrap="nowrap">
      <StatusChip status={props.status} disabled={props.disabled} onChange={props.onStatus} />
      <VisitedToggle
        visited={props.visited}
        disabled={props.disabled}
        onChange={props.onVisited}
      />
    </Group>
  );
}
