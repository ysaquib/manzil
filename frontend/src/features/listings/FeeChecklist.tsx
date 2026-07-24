// Fees checklist (P1-11, §9.5): fee slots with extracted / manual / unknown
// states, split into monthly (composes into all-in) and one-time / move-in
// (display-only, §20 2026-07-18) sections. Manual fill-ins stage in the
// drawer draft until Save. Presentation: grid rows with a state dot at the
// front and a flush-right amount (the dot color mirrors STATE_COLOR).
import {
  ActionIcon,
  Badge,
  Button,
  NumberInput,
  Popover,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconArrowBackUp, IconPencil, IconUserEdit } from "@tabler/icons-react";
import { useState } from "react";

import classes from "./FeeChecklist.module.css";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { basisLabel, feeForSlot, moveInEstimate, type Household } from "./oneTimeFees";
import {
  MONTHLY_FEE_SLOTS,
  ONE_TIME_FEE_SLOTS,
  type FeeEntry,
  type OneTimeFee,
} from "./types";

// STATE_COLOR's meaning now drives the state dot's color (via the module CSS
// class of the same name): extracted=green, manual=plum, estimated=yellow,
// unknown=hollow ring.
const STATE_CLASS: Record<FeeEntry["value_state"], string> = {
  extracted: classes.extracted,
  manual: classes.manual,
  estimated: classes.estimated,
  unknown: classes.unknown,
};

function FeeRow({
  slot,
  label,
  subtitle,
  entry,
  monthly,
  enteredByName,
  original,
}: {
  slot: string;
  label: string;
  subtitle?: string;
  entry: FeeEntry | undefined;
  monthly: boolean;
  enteredByName?: string;
  /** the extraction-derived amount a revert restores; undefined → unknown */
  original?: number;
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
    <div className={classes.row}>
      <div className={classes.name}>
        <span
          data-testid={`fee-state-${slot}`}
          data-state={state}
          className={`${classes.qd} ${STATE_CLASS[state]}`}
          title={state}
        />
        {label}
        {subtitle && <div className={classes.sub}>{subtitle}</div>}
      </div>
      <div className={classes.amt}>
        {displayAmount != null ? (
          `$${displayAmount.toLocaleString()}`
        ) : (
          <span className={classes.dim}>unknown</span>
        )}
      </div>
      <div className={classes.actions}>
        {isPending ? (
          <Badge size="xs" color={"manual"} variant="light">
            pending
          </Badge>
        ) : (
          state === "manual" && (
            <>
              <Tooltip label={`Entered manually${enteredByName ? ` by ${enteredByName}` : ""}`}>
                <IconUserEdit
                  size={14}
                  stroke={1.5}
                  color="var(--mantine-color-dimmed)"
                  aria-label="manual entry"
                />
              </Tooltip>
              <Tooltip
                label={
                  original !== undefined
                    ? "Revert to the extracted amount"
                    : "Revert to unknown (nothing was extracted)"
                }
              >
                <ActionIcon
                  color="gray"
                  size="sm"
                  variant="subtle"
                  aria-label={`revert ${label}`}
                  onClick={() =>
                    setDraftFee(slot, {
                      amount: original ?? null,
                      state: original !== undefined ? "extracted" : "unknown",
                    })
                  }
                >
                  <IconArrowBackUp
                    size={14}
                    stroke={1.5}
                    color="var(--mantine-color-dimmed)"
                  />
                </ActionIcon>
              </Tooltip>
            </>
          )
        )}
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
      </div>
    </div>
  );
}

export function FeeChecklist({
  fees,
  oneTimeFees = [],
  household,
  memberNames,
  feeOriginals,
}: {
  fees: FeeEntry[];
  /** the `one_time_fees` extraction's fee list, for basis subtitles + estimate */
  oneTimeFees?: OneTimeFee[];
  /** hunt household settings, for the per-person / per-pet move-in estimate */
  household?: Household;
  /** user_id → display name, for the manual-entry attribution tooltip */
  memberNames?: Map<string, string>;
  /** slot → extraction-derived amount a revert restores */
  feeOriginals?: Map<string, number>;
}) {
  const bySlot = new Map(fees.map((entry) => [entry.fee_slot, entry]));
  const nameFor = (entry: FeeEntry | undefined) =>
    entry?.entered_by
      ? (memberNames?.get(entry.entered_by) ?? entry.entered_by)
      : undefined;
  const estimate = household ? moveInEstimate(oneTimeFees, household) : null;
  return (
    <Stack gap={4}>
      <div className={classes.list}>
        <div className={classes.subhead}>Monthly</div>
        {MONTHLY_FEE_SLOTS.map(({ slot, label }) => (
          <FeeRow
            key={slot}
            slot={slot}
            label={label}
            entry={bySlot.get(slot)}
            monthly
            enteredByName={nameFor(bySlot.get(slot))}
            original={feeOriginals?.get(slot)}
          />
        ))}
        <div className={classes.subhead}>Move-in &amp; one-time</div>
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
              original={feeOriginals?.get(slot)}
            />
          );
        })}
      </div>
      {estimate !== null && (
        <Text size="xs" c="dimmed">
          Est. move-in fees for your household: ${estimate.toLocaleString()} (excludes
          security deposit)
        </Text>
      )}
    </Stack>
  );
}
