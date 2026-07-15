// Fees checklist (P1-11, §9.5): fee slots with extracted / manual / unknown states.
// Manual fill-ins stage in the drawer draft until Save.
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  NumberInput,
  Popover,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconPencil, IconUserEdit } from "@tabler/icons-react";
import { useState } from "react";

import { useListingDetailDraft } from "./ListingDetailDraft";
import { FEE_SLOTS, type FeeEntry } from "./types";

const STATE_COLOR: Record<FeeEntry["value_state"], string> = {
  extracted: "green",
  manual: "primary",
  estimated: "yellow",
  unknown: "gray",
};

function FeeRow({
  slot,
  label,
  entry,
}: {
  slot: string;
  label: string;
  entry: FeeEntry | undefined;
}) {
  const { draftFees, setDraftFee } = useListingDetailDraft();
  const [opened, setOpened] = useState(false);
  const draftEntry = draftFees.get(slot);
  const [amount, setAmount] = useState<number | "">("");

  const isPending = draftEntry !== undefined;
  const state = entry?.value_state ?? "unknown";
  const displayAmount = isPending ? draftEntry.amount : entry?.amount;

  const open = () => {
    setAmount(draftEntry?.amount ?? entry?.amount ?? "");
    setOpened(true);
  };

  const apply = () => {
    setDraftFee(slot, { amount: amount === "" ? null : amount });
    setOpened(false);
  };

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{label}</Text>
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" fw={600} c={displayAmount == null ? "dimmed" : undefined}>
            {displayAmount != null ? `$${displayAmount.toLocaleString()}/mo` : "unknown"}
          </Text>
          {isPending ? (
            <Badge size="xs" color={"manual"} variant="light">
              pending
            </Badge>
          ) : (
            <>
              <Badge size="xs" variant="light" color={STATE_COLOR[state]}>
                {state}
              </Badge>
              {state === "manual" && (
                <Tooltip
                  label={`Entered manually${entry?.entered_by ? ` by ${entry.entered_by}` : ""}`}
                >
                  <IconUserEdit
                    size={14}
                    stroke={1.5}
                    color="var(--mantine-color-dimmed)"
                    aria-label="manual entry"
                  />
                </Tooltip>
              )}
            </>
          )}
        </Group>
      </Table.Td>
      <Table.Td width={40}>
        <Popover opened={opened} onChange={setOpened} width={220} position="bottom-end" withArrow>
          <Popover.Target>
            <Tooltip label="Fill in" openDelay={450}>
              <ActionIcon
                color="gray"
                size="sm"
                variant="subtle"
                onClick={open}
                aria-label={`edit ${label}`}
              >
                <IconPencil size={14} stroke={1.5} color="var(--mantine-color-dimmed)" />
              </ActionIcon>
            </Tooltip>
          </Popover.Target>
          <Popover.Dropdown>
            <Stack gap="xs">
              <NumberInput
                label="Monthly amount"
                prefix="$"
                min={0}
                value={amount}
                onChange={(next) => setAmount(typeof next === "number" ? next : "")}
              />
              <Button size="xs" onClick={apply}>
                Apply
              </Button>
            </Stack>
          </Popover.Dropdown>
        </Popover>
      </Table.Td>
    </Table.Tr>
  );
}

export function FeeChecklist({ fees }: { fees: FeeEntry[] }) {
  const bySlot = new Map(fees.map((entry) => [entry.fee_slot, entry]));
  return (
    <Table verticalSpacing="xs" withRowBorders={false}>
      <Table.Tbody>
        {FEE_SLOTS.map(({ slot, label }) => (
          <FeeRow key={slot} slot={slot} label={label} entry={bySlot.get(slot)} />
        ))}
      </Table.Tbody>
    </Table>
  );
}
