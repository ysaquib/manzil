// Fees checklist (P1-11, §9.5): fee slots with extracted / manual / unknown
// states, split into monthly (composes into all-in) and one-time / move-in
// (display-only, §20 2026-07-18) sections. Manual fill-ins stage in the
// drawer draft until Save.
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
import { basisLabel, feeForSlot, moveInEstimate, type Household } from "./oneTimeFees";
import {
  MONTHLY_FEE_SLOTS,
  ONE_TIME_FEE_SLOTS,
  type FeeEntry,
  type OneTimeFee,
} from "./types";

const STATE_COLOR: Record<FeeEntry["value_state"], string> = {
  extracted: "green",
  manual: "primary",
  estimated: "yellow",
  unknown: "gray",
};

function FeeRow({
  slot,
  label,
  subtitle,
  entry,
  monthly,
  enteredByName,
}: {
  slot: string;
  label: string;
  subtitle?: string;
  entry: FeeEntry | undefined;
  monthly: boolean;
  enteredByName?: string;
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
        {subtitle && (
          <Text size="xs" c="dimmed">
            {subtitle}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" fw={600} c={displayAmount == null ? "dimmed" : undefined}>
            {displayAmount != null
              ? `$${displayAmount.toLocaleString()}${monthly ? "/mo" : ""}`
              : "unknown"}
          </Text>
          {isPending ? (
            <Badge size="xs" color={"manual"} variant="light">
              pending
            </Badge>
          ) : (
            <>
              {/* "unknown" already reads as the amount — a badge repeating it
                  is noise, so badge only the states that add information. */}
              {state !== "unknown" && (
                <Badge size="xs" variant="light" color={STATE_COLOR[state]}>
                  {state}
                </Badge>
              )}
              {state === "manual" && (
                <Tooltip label={`Entered manually${enteredByName ? ` by ${enteredByName}` : ""}`}>
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
                label={monthly ? "Monthly amount" : "One-time amount"}
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

function SectionLabel({ children }: { children: string }) {
  return (
    <Table.Tr>
      <Table.Td colSpan={3} pb={2} pt="xs">
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          {children}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}

export function FeeChecklist({
  fees,
  oneTimeFees = [],
  household,
  memberNames,
}: {
  fees: FeeEntry[];
  /** the `one_time_fees` extraction's fee list, for basis subtitles + estimate */
  oneTimeFees?: OneTimeFee[];
  /** hunt household settings, for the per-person / per-pet move-in estimate */
  household?: Household;
  /** user_id → display name, for the manual-entry attribution tooltip */
  memberNames?: Map<string, string>;
}) {
  const bySlot = new Map(fees.map((entry) => [entry.fee_slot, entry]));
  const nameFor = (entry: FeeEntry | undefined) =>
    entry?.entered_by
      ? (memberNames?.get(entry.entered_by) ?? entry.entered_by)
      : undefined;
  const estimate = household ? moveInEstimate(oneTimeFees, household) : null;
  return (
    <Stack gap={4}>
      <Table verticalSpacing="xs" withRowBorders={false}>
        <Table.Tbody>
          <SectionLabel>Monthly</SectionLabel>
          {MONTHLY_FEE_SLOTS.map(({ slot, label }) => (
            <FeeRow
              key={slot}
              slot={slot}
              label={label}
              entry={bySlot.get(slot)}
              monthly
              enteredByName={nameFor(bySlot.get(slot))}
            />
          ))}
          <SectionLabel>One-time / move-in</SectionLabel>
          {ONE_TIME_FEE_SLOTS.map(({ slot, label }) => {
            const extracted = feeForSlot(oneTimeFees, slot);
            return (
              <FeeRow
                key={slot}
                slot={slot}
                label={label}
                subtitle={extracted ? basisLabel(extracted) || undefined : undefined}
                entry={bySlot.get(slot)}
                monthly={false}
                enteredByName={nameFor(bySlot.get(slot))}
              />
            );
          })}
        </Table.Tbody>
      </Table>
      {estimate !== null && (
        <Text size="xs" c="dimmed">
          Est. move-in fees for your household: ${estimate.toLocaleString()} (excludes
          security deposit)
        </Text>
      )}
    </Stack>
  );
}
