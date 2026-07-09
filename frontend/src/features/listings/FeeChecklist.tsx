// Fees checklist (P1-11, §9.5): the standard fee slots with extracted /
// manual / unknown states. Manual entries carry the person-pencil marker with
// attribution on hover — unmistakable from agent-sourced values. Unknown slots
// keep contributing unknown; an unfilled checklist never improves a score.
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
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { ApiError } from "../../lib/apiClient";
import { semantic } from "../../theme";
import { useUpsertFee } from "./api";
import { FEE_SLOTS, type FeeEntry } from "./types";

const STATE_COLOR: Record<FeeEntry["value_state"], string> = {
  extracted: "green",
  manual: semantic.manual,
  estimated: semantic.estimated,
  unknown: "gray",
};

function FeeRow({
  huntId,
  listingId,
  slot,
  label,
  entry,
}: {
  huntId: string;
  listingId: string;
  slot: string;
  label: string;
  entry: FeeEntry | undefined;
}) {
  const upsertFee = useUpsertFee(huntId, listingId);
  const [opened, setOpened] = useState(false);
  const [amount, setAmount] = useState<number | "">(entry?.amount ?? "");

  const state = entry?.value_state ?? "unknown";

  const save = () =>
    upsertFee.mutate(
      { slot, amount: amount === "" ? null : amount, value_state: "manual" },
      {
        onSuccess: () => setOpened(false),
        onError: (error) =>
          notifications.show({
            title: "Couldn't save fee",
            message: error instanceof ApiError ? error.message : "Unexpected error",
            color: "red",
          }),
      },
    );

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{label}</Text>
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" fw={600} c={state === "unknown" ? "dimmed" : undefined}>
            {entry?.amount != null ? `$${entry.amount.toLocaleString()}/mo` : "unknown"}
          </Text>
          <Badge size="xs" variant="light" color={STATE_COLOR[state]}>
            {state}
          </Badge>
          {state === "manual" && (
            <Tooltip label={`Entered manually${entry?.entered_by ? ` by ${entry.entered_by}` : ""}`}>
              <Text size="xs" aria-label="manual entry">
                ✎👤
              </Text>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td width={40}>
        <Popover opened={opened} onChange={setOpened} width={220} position="bottom-end" withArrow>
          <Popover.Target>
            <Tooltip label="Fill in after a leasing-office call">
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={() => {
                  setAmount(entry?.amount ?? "");
                  setOpened(true);
                }}
                aria-label={`edit ${label}`}
              >
                ✎
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
              <Button size="xs" onClick={save} loading={upsertFee.isPending}>
                Save
              </Button>
            </Stack>
          </Popover.Dropdown>
        </Popover>
      </Table.Td>
    </Table.Tr>
  );
}

export function FeeChecklist({
  huntId,
  listingId,
  fees,
}: {
  huntId: string;
  listingId: string;
  fees: FeeEntry[];
}) {
  const bySlot = new Map(fees.map((entry) => [entry.fee_slot, entry]));
  return (
    <Table verticalSpacing="xs" withRowBorders={false}>
      <Table.Tbody>
        {FEE_SLOTS.map(({ slot, label }) => (
          <FeeRow
            key={slot}
            huntId={huntId}
            listingId={listingId}
            slot={slot}
            label={label}
            entry={bySlot.get(slot)}
          />
        ))}
      </Table.Tbody>
    </Table>
  );
}
