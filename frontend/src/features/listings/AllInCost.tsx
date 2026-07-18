// §9.5 P3-9 all-in cost UI: the Overview cell with the estimated portion
// visually distinct (`$1,845 (~$210 est.)`, §13.2) and the drawer's component
// breakdown with actual/estimated/unknown tags. Reads
// hunt_listings.all_in_components (display metadata) — the pinned
// scores.breakdown stays the scoring truth.
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  NumberInput,
  Popover,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconAlertTriangle, IconArrowBackUp, IconPencil, IconUserEdit } from "@tabler/icons-react";
import { useState } from "react";

import { useListingDetailDraft } from "./ListingDetailDraft";
import { REVERT_NOTE } from "./overrides";
import type { AllInComponents } from "./types";

const BADGE_COPY: Record<string, string> = {
  fees_unverified: "Fees unverified",
  heat_unknown: "Heating type unknown",
  utilities_not_estimated: "Utilities not estimated",
};

const BADGE_HINT: Record<string, string> = {
  fees_unverified:
    "The page did not state utility inclusions or a needed estimate is missing — the all-in figure may be incomplete.",
  heat_unknown:
    "Heating fuel unknown — the costlier of the gas-heat and electric-heat estimates is used.",
  utilities_not_estimated:
    "No utility baselines exist for this metro yet — the all-in excludes utility estimates.",
};

const TAG_COLOR: Record<string, string> = {
  actual: "green",
  estimated: "yellow",
  unknown: "gray",
};

function CompositionBadges({ badges }: { badges: string[] }) {
  return (
    <>
      {badges.map((badge) => (
        <Tooltip key={badge} label={BADGE_HINT[badge] ?? badge} multiline w={260}>
          <Badge size="xs" color="yellow" variant="light">
            {BADGE_COPY[badge] ?? badge}
          </Badge>
        </Tooltip>
      ))}
    </>
  );
}

/** One quiet triangle instead of a chip per warning (§13.2 declutter): hover
 * lists the warning titles; the drawer keeps the full explanations. */
export function AllInWarningIcon({ badges }: { badges: string[] }) {
  if (badges.length === 0) return null;
  return (
    <Tooltip
      label={
        <Stack gap={2}>
          {badges.map((badge) => (
            <Text size="xs" key={badge}>
              {BADGE_COPY[badge] ?? badge}
            </Text>
          ))}
        </Stack>
      }
    >
      <Box c="yellow.6" display="flex" style={{ flexShrink: 0 }}>
        <IconAlertTriangle
          size={14}
          stroke={1.75}
          aria-label={`${badges.length} all-in warning${badges.length > 1 ? "s" : ""}`}
        />
      </Box>
    </Tooltip>
  );
}

/** Overview all-in cell. `allIn` is the scored value from the row's breakdown;
 * the composition (per-plan, display) supplies the estimated portion and
 * warnings. */
export function AllInCell({
  allIn,
  composition,
}: {
  allIn: number | null;
  composition: AllInComponents | null;
}) {
  const est = composition?.estimated_total ?? 0;
  const badges = composition?.badges ?? [];
  const overridden = composition?.overridden === true;
  return (
    <Group gap={6} wrap="nowrap">
      <Text size="sm">{allIn === null ? "—" : `$${allIn.toLocaleString()}`}</Text>
      {overridden ? (
        <Tooltip label="Overridden manually — see the drawer for the composed figure">
          <Box c="dimmed" display="flex" style={{ flexShrink: 0 }}>
            <IconUserEdit size={14} stroke={1.5} aria-label="all-in overridden" />
          </Box>
        </Tooltip>
      ) : (
        allIn !== null &&
        est > 0 && (
          <Text size="xs" c="dimmed">
            (~${est.toLocaleString()} est.)
          </Text>
        )
      )}
      <AllInWarningIcon badges={badges} />
    </Group>
  );
}

/** Drawer section: the §9.5 component breakdown with tags. */
export function AllInBreakdown({ composition }: { composition: AllInComponents | null }) {
  if (composition === null) {
    return (
      <Text size="sm" c="dimmed">
        No composition yet — ingestion may still be running.
      </Text>
    );
  }
  return (
    <Stack gap="xs">
      {composition.badges.length > 0 && (
        <Group gap={6}>
          <CompositionBadges badges={composition.badges} />
        </Group>
      )}
      <Table verticalSpacing={4} withRowBorders={false}>
        <Table.Tbody>
          {composition.components.map((component, index) => (
            <Table.Tr key={`${component.name}:${index}`}>
              <Table.Td>
                <Text size="sm">{component.name.replaceAll("_", " ")}</Text>
                {component.note && (
                  <Text size="xs" c="dimmed">
                    {component.note}
                  </Text>
                )}
              </Table.Td>
              <Table.Td width={100}>
                <Text size="sm" ta="right">
                  {component.amount === null ? "unknown" : `$${component.amount.toLocaleString()}`}
                </Text>
              </Table.Td>
              <Table.Td width={90}>
                <Badge size="xs" color={TAG_COLOR[component.tag] ?? "gray"} variant="light">
                  {component.tag}
                </Badge>
              </Table.Td>
            </Table.Tr>
          ))}
          <Table.Tr>
            <Table.Td>
              <Group gap="xs" wrap="nowrap">
                <Text size="sm" fw={600}>
                  All-in / mo ({composition.mode})
                </Text>
                {composition.overridden && (
                  <Badge size="xs" color="manual" variant="light">
                    override
                  </Badge>
                )}
              </Group>
            </Table.Td>
            <Table.Td width={100}>
              <Text size="sm" fw={600} ta="right">
                {composition.total === null
                  ? "unknown"
                  : `$${composition.total.toLocaleString()}`}
              </Text>
            </Table.Td>
            <Table.Td width={90} />
          </Table.Tr>
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

/** Drawer-only override affordance for the all-in figure (§9.6): stages an
 * `all_in_monthly` draft override; reverting stages the null tombstone. Must
 * render inside ListingDetailDraftProvider. */
export function AllInOverrideControl({ overridden }: { overridden: boolean }) {
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const [opened, setOpened] = useState(false);
  const [amount, setAmount] = useState<number | "">("");
  const [note, setNote] = useState("");

  const draft = draftOverrides.get("all_in_monthly");
  const isPending = draft !== undefined;

  const apply = () => {
    if (amount === "") return;
    setDraftOverride("all_in_monthly", { value: amount, note: note.trim() || null });
    setOpened(false);
  };

  return (
    <Group gap="xs" wrap="nowrap">
      {isPending && (
        <Badge size="xs" color="manual" variant="light">
          pending
        </Badge>
      )}
      <Popover opened={opened} onChange={setOpened} width={240} position="bottom-end" withArrow>
        <Popover.Target>
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            leftSection={<IconPencil size={12} stroke={1.5} />}
            onClick={() => {
              setAmount(typeof draft?.value === "number" ? draft.value : "");
              setNote(draft?.note ?? "");
              setOpened(true);
            }}
          >
            Override all-in
          </Button>
        </Popover.Target>
        <Popover.Dropdown>
          <Stack gap="xs">
            <NumberInput
              label="All-in monthly"
              prefix="$"
              min={0}
              value={amount}
              onChange={(next) => setAmount(typeof next === "number" ? next : "")}
            />
            <TextInput
              label="Note"
              placeholder="e.g. leasing office quote"
              value={note}
              onChange={(e) => setNote(e.currentTarget.value)}
            />
            <Button size="xs" onClick={apply} disabled={amount === ""}>
              Apply
            </Button>
          </Stack>
        </Popover.Dropdown>
      </Popover>
      {overridden && !isPending && (
        <Tooltip label="Revert to the composed figure">
          <ActionIcon
            color="gray"
            size="sm"
            variant="subtle"
            aria-label="revert all-in override"
            onClick={() => setDraftOverride("all_in_monthly", { value: null, note: REVERT_NOTE })}
          >
            <IconArrowBackUp size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
}
