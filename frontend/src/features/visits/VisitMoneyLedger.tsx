// The money ledger (VC-7, DESIGN §9.7).
//
// A tour produces the best cost data in the system: figures a human confirmed
// aloud, standing in the leasing office, while the machine's numbers came off a
// marketing page. So this shows both — what the Listing currently believes,
// beside what the agent actually said — and offers the difference to the
// Listing rather than writing it.
//
// Nothing here mutates a Listing. Proposing is an offer; the decision lives in
// the drawer, where the person who owns the cost data is already looking.
import {
  ActionIcon,
  Badge,
  Card,
  Group,
  NumberInput,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconCheck, IconSend, IconX } from "@tabler/icons-react";
import { useState } from "react";

import type { AllInComponents, Listing } from "../listings/types";
import { useCreateFeeProposal, useWithdrawFeeProposal } from "./api";
import type { VisitFeeProposal, VisitUnit } from "./types";
import classes from "./VisitMoneyLedger.module.css";

/** What a tour can offer, and where each figure lands if accepted. */
interface LedgerLine {
  target: "fee_slot" | "override";
  targetKey: string;
  label: string;
  /** Names in `all_in_components` that mean this line, lowercased. */
  aliases: string[];
}

export const LEDGER_LINES: LedgerLine[] = [
  { target: "override", targetKey: "base_rent", label: "Base rent", aliases: ["base rent", "rent"] },
  {
    target: "override",
    targetKey: "all_in_monthly",
    label: "Total monthly",
    aliases: ["all-in", "total"],
  },
  { target: "fee_slot", targetKey: "parking", label: "Parking", aliases: ["parking", "garage"] },
  { target: "fee_slot", targetKey: "pet_rent", label: "Pet rent", aliases: ["pet rent"] },
  {
    target: "fee_slot",
    targetKey: "water_sewer",
    label: "Water / sewer",
    aliases: ["water", "sewer"],
  },
  { target: "fee_slot", targetKey: "valet_trash", label: "Trash", aliases: ["trash", "waste"] },
  {
    target: "fee_slot",
    targetKey: "insurance_program",
    label: "Insurance program",
    aliases: ["insurance", "liability"],
  },
  {
    target: "fee_slot",
    targetKey: "application_fee",
    label: "Application fee",
    aliases: ["application"],
  },
  { target: "fee_slot", targetKey: "admin", label: "Admin fee", aliases: ["admin"] },
  { target: "fee_slot", targetKey: "pet_deposit", label: "Pet deposit", aliases: ["pet deposit"] },
  { target: "fee_slot", targetKey: "pet_fee", label: "Pet fee", aliases: ["pet fee"] },
];

/**
 * What the Listing currently believes this line costs.
 *
 * Read from the composed `all_in_components` rather than a fee table, because
 * that is the number the reader actually sees everywhere else; showing a
 * different one here would make the comparison meaningless.
 */
export function listingFigure(
  line: LedgerLine,
  composition: AllInComponents | null | undefined,
): { amount: number | null; tag: string | null } {
  if (line.targetKey === "all_in_monthly") {
    return { amount: composition?.total ?? null, tag: composition?.total == null ? null : "actual" };
  }
  // The composer names the rent component exactly "rent"; everything else
  // matches loosely, because fee component names come from the page.
  const match = composition?.components?.find((component) =>
    line.targetKey === "base_rent"
      ? component.name === "rent"
      : line.aliases.some((alias) => component.name.toLowerCase().includes(alias)),
  );
  if (!match) return { amount: null, tag: null };
  return { amount: match.amount, tag: match.tag };
}

export function formatMoney(amount: number | null): string {
  if (amount === null) return "—";
  return `$${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function LedgerRow({
  line,
  listing,
  proposal,
  onPropose,
  onWithdraw,
  busy,
  readOnly,
}: {
  line: LedgerLine;
  listing: Listing;
  proposal: VisitFeeProposal | undefined;
  onPropose: (line: LedgerLine, amount: number) => void;
  onWithdraw: (proposal: VisitFeeProposal) => void;
  busy: boolean;
  readOnly: boolean;
}) {
  const [draft, setDraft] = useState<number | string>("");
  const current = listingFigure(line, listing.all_in_components);

  return (
    <Group className={classes.row} wrap="nowrap" gap="sm" align="center">
      <Stack gap={0} className={classes.label}>
        <Text size="sm">{line.label}</Text>
        <Text size="xs" c="dimmed">
          Listing says {formatMoney(current.amount)}
          {current.tag === "estimated" && " (est.)"}
        </Text>
      </Stack>

      {proposal ? (
        <Group gap={6} wrap="nowrap">
          <Badge size="sm" variant="light" color="ochre" className={classes.proposed}>
            Offered {formatMoney(Number(proposal.amount))}
          </Badge>
          {!readOnly && (
            <Tooltip label="Withdraw this offer">
              <ActionIcon
                size="sm"
                variant="subtle"
                color="gray"
                aria-label={`Withdraw ${line.label} offer`}
                onClick={() => onWithdraw(proposal)}
                disabled={busy}
              >
                <IconX size={14} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      ) : (
        <Group gap={6} wrap="nowrap">
          <NumberInput
            size="xs"
            w={110}
            min={0}
            prefix="$"
            hideControls
            placeholder="Confirmed"
            aria-label={`${line.label} confirmed on the tour`}
            value={draft}
            onChange={setDraft}
            disabled={readOnly || busy}
          />
          <Tooltip label="Offer this figure to the listing">
            <ActionIcon
              size="lg"
              variant="light"
              aria-label={`Propose ${line.label}`}
              disabled={readOnly || busy || draft === "" || draft === null}
              onClick={() => {
                const amount = Number(draft);
                if (Number.isFinite(amount)) {
                  onPropose(line, amount);
                  setDraft("");
                }
              }}
            >
              <IconSend size={15} />
            </ActionIcon>
          </Tooltip>
        </Group>
      )}
    </Group>
  );
}

/**
 * The ledger. Renders nothing when the Visit's Property has no Listing in this
 * Hunt — there would be nowhere for a figure to go.
 */
export function VisitMoneyLedger({
  visitId,
  listing,
  proposals,
  activeUnit,
  readOnly = false,
}: {
  visitId: string;
  listing: Listing | undefined;
  proposals: VisitFeeProposal[];
  activeUnit: VisitUnit | null;
  readOnly?: boolean;
}) {
  const create = useCreateFeeProposal(visitId);
  const withdraw = useWithdrawFeeProposal(visitId);

  if (!listing) return null;

  const pending = new Map(
    proposals.filter((p) => p.status === "pending").map((p) => [`${p.target}:${p.target_key}`, p]),
  );
  const busy = create.isPending || withdraw.isPending;

  return (
    <Card padding="sm">
      <Stack gap="xs">
        <Group justify="space-between" gap="sm" wrap="wrap">
          <Text fw={600} size="sm">
            Money confirmed on the tour
          </Text>
          {pending.size > 0 && (
            <Badge size="sm" variant="light" color="ochre" leftSection={<IconCheck size={11} />}>
              {pending.size === 1 ? "1 figure offered" : `${pending.size} figures offered`}
            </Badge>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          These are offers, not edits. Nothing on the listing changes until someone accepts them in
          Cost &amp; fees.
        </Text>

        <Stack gap={0}>
          {LEDGER_LINES.map((line) => (
            <LedgerRow
              key={`${line.target}:${line.targetKey}`}
              line={line}
              listing={listing}
              proposal={pending.get(`${line.target}:${line.targetKey}`)}
              busy={busy}
              readOnly={readOnly}
              onPropose={(target, amount) =>
                create.mutate({
                  hunt_listing_id: listing.id,
                  // Monthly charges belong to the door you were standing in;
                  // application and admin fees are the building's.
                  visit_unit_id:
                    target.target === "override" || target.targetKey.startsWith("pet_rent")
                      ? (activeUnit?.id ?? null)
                      : null,
                  target: target.target,
                  target_key: target.targetKey,
                  amount,
                })
              }
              onWithdraw={(proposal) => withdraw.mutate(proposal.id)}
            />
          ))}
        </Stack>
      </Stack>
    </Card>
  );
}
