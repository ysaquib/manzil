// §9.5 + P3-SC8: the consolidated Cost & fees section. One surface replaces the
// old split of Cost Breakdown (read-only arithmetic) and Fees (the correction
// surface), because every line here is overrideable and the split forced the
// same charge to appear twice.
//
// The row grammar is uniform: state dot · label · status icons · reason
// subline · amount · one action. Qualifiers that are the normal case (mandatory,
// non-refundable, included) are icons or plain typography, not chips — colour
// and chips are reserved for the few states that can mislead you (not counted,
// unknown, disputed, pending, incomplete).
//
// Typographic encodings, all deliberate:
//   - not counted → the row dims and the figure is struck through
//   - entered by a person → the figure carries a dotted underline
//   - pending (unsaved) → dashed dot and chip, distinct from a saved override
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  NumberInput,
  Popover,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import {
  IconArrowBackUp,
  IconCashBanknote,
  IconCashBanknoteMoveBack,
  IconCashBanknoteOff,
  IconCheck,
  IconCircleCheck,
  IconPencil,
  IconX,
} from "@tabler/icons-react";
import { useState, type ReactNode } from "react";

import classes from "./CostAndFees.module.css";
import drawer from "./ListingDetailDrawer.module.css";
import { useListingDetailDraft } from "./ListingDetailDraft";
import { REVERT_NOTE } from "./overrides";
import { effectiveUtilitiesIncluded } from "./utilitiesIncluded";
import { basisLabel, feeForSlot, type Household } from "./oneTimeFees";
import {
  FEE_SLOTS,
  MONTHLY_FEE_SLOTS,
  MOVE_IN_LINE_LABELS,
  ONE_TIME_FEE_SLOTS,
  type AllInComponents,
  type FeeEntry,
  type MoveInCharge,
  type MoveInComponents,
  type OneTimeFee,
  type UtilityName,
  type UtilityOverride,
} from "./types";
import { memberDisplayName } from "../collaboration/memberDisplay";
import type { HuntMember } from "../collaboration/api";
import { useDecideFeeProposal } from "../visits/api";
import type { VisitFeeProposal } from "../visits/types";

const STATE_CLASS: Record<string, string> = {
  actual: drawer.stateDotActual,
  extracted: drawer.stateDotExtracted,
  estimated: drawer.stateDotEstimated,
  manual: drawer.stateDotManual,
  unknown: drawer.stateDotUnknown,
};

const UTILITY_ROWS: { utility: UtilityName; label: string; amountEditable: boolean }[] = [
  { utility: "electric", label: "Electricity", amountEditable: true },
  { utility: "gas", label: "Gas", amountEditable: true },
  { utility: "water", label: "Water", amountEditable: true },
  { utility: "sewer", label: "Sewer", amountEditable: true },
  { utility: "cooling", label: "Cooling", amountEditable: false },
  { utility: "heat", label: "Heat", amountEditable: true },
  { utility: "trash", label: "Trash", amountEditable: true },
];

const MAJOR_UTILITIES = new Set(["electric", "gas", "water", "heat"]);

const BADGE_COPY: Record<string, string> = {
  fees_unverified: "Fees unverified",
  heat_unknown: "Heating type unknown",
  utilities_not_estimated: "Utilities not estimated",
  move_in_incomplete: "Incomplete",
};

const BADGE_HINT: Record<string, string> = {
  fees_unverified:
    "The page did not state utility inclusions or a needed estimate is missing — the all-in figure may be incomplete.",
  heat_unknown:
    "Heating fuel unknown — the costlier of the gas-heat and electric-heat estimates is used.",
  utilities_not_estimated:
    "No utility baselines exist for this location yet — the all-in excludes utility estimates.",
  move_in_incomplete:
    "A charge you have to pay has no stated amount, so this is what is known so far — not a total.",
};

function money(amount: number | null | undefined): string {
  return amount == null ? "—" : `$${amount.toLocaleString()}`;
}

/** Refundability, credit and inclusion ride as icons: they are the normal case
 * on most charges, and a row of pills for the normal case buries the
 * exceptions. Colour carries the meaning — sage refunds, brick does not,
 * ochre sits between the two because a credited charge neither leaves nor
 * stays. */
function StatusIcons({
  refundable,
  credited,
  included,
}: {
  refundable?: boolean | null;
  credited?: boolean;
  included?: boolean;
}) {
  return (
    <>
      {included && (
        <Tooltip label="Included in rent">
          <Box component="span" className={classes.icon} data-tone="included">
            <IconCircleCheck size={14} stroke={1.7} aria-label="included in rent" />
          </Box>
        </Tooltip>
      )}
      {credited && (
        <Tooltip label="Credited to first month's rent">
          <Box component="span" className={classes.icon} data-tone="credited">
            <IconCashBanknoteMoveBack size={15} stroke={1.7} aria-label="credited" />
          </Box>
        </Tooltip>
      )}
      {refundable === true && (
        <Tooltip label="Refundable">
          <Box component="span" className={classes.icon} data-tone="refundable">
            <IconCashBanknote size={15} stroke={1.7} aria-label="refundable" />
          </Box>
        </Tooltip>
      )}
      {refundable === false && (
        <Tooltip label="Non-refundable">
          <Box component="span" className={classes.icon} data-tone="nonRefundable">
            <IconCashBanknoteOff size={15} stroke={1.7} aria-label="non-refundable" />
          </Box>
        </Tooltip>
      )}
    </>
  );
}

function CompositionBadges({ badges }: { badges: string[] }) {
  return (
    <>
      {badges.map((badge) => (
        <Tooltip key={badge} label={BADGE_HINT[badge] ?? badge} multiline w={260}>
          <Badge size="xs" color={badge === "move_in_incomplete" ? "red" : "yellow"} variant="light">
            {BADGE_COPY[badge] ?? badge}
          </Badge>
        </Tooltip>
      ))}
    </>
  );
}

/** The shared row. When a figure is modified, `action` is a revert control only;
 * otherwise it is the edit popover and the pencil hides until hover or focus. */
function CostRow({
  label,
  state,
  testId,
  subline,
  amount,
  amountText,
  counted = true,
  manual = false,
  pending = false,
  icons,
  chips,
  action,
  hoverRevealAction = false,
}: {
  label: string;
  state: string;
  testId?: string;
  subline?: ReactNode;
  amount?: number | null;
  amountText?: string;
  counted?: boolean;
  manual?: boolean;
  pending?: boolean;
  icons?: ReactNode;
  chips?: ReactNode;
  action?: ReactNode;
  hoverRevealAction?: boolean;
}) {
  const text = amountText ?? money(amount);
  return (
    <Box
      className={`${drawer.ledgerRow} ${classes.row}`}
      data-counted={counted ? "yes" : "no"}
      data-pending={pending ? "true" : undefined}
      data-hover-reveal={hoverRevealAction ? "true" : undefined}
    >
      <Box className={classes.name}>
        <Box
          component="span"
          data-testid={testId}
          data-state={pending ? "pending" : state}
          className={`${drawer.stateDot} ${pending ? classes.dotPending : STATE_CLASS[state]}`}
          title={pending ? "pending" : state}
        />
        <Text size="sm" component="span">
          {label}
        </Text>
        {icons}
        {chips}
        {subline ? (
          <Text component="span" size="xs" c="dimmed" className={drawer.ledgerSubline}>
            {subline}
          </Text>
        ) : null}
      </Box>
      <Group gap={4} wrap="nowrap" className={classes.valueAction}>
        <Text
          size="sm"
          fw={600}
          ta="right"
          className={`${drawer.tabularNums} ${classes.amount}`}
          data-manual={manual ? "true" : undefined}
          data-struck={!counted && amount != null ? "true" : undefined}
        >
          {amount == null && amountText === undefined ? (
            <Text component="span" c="dimmed" fs="italic" fw={500}>
              unknown
            </Text>
          ) : (
            text
          )}
        </Text>
        {action ?? <ActionSlotPlaceholder />}
      </Group>
    </Box>
  );
}

function RevertButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Tooltip label="Revert to original value">
      <ActionIcon
        color="gray"
        size="sm"
        variant="subtle"
        aria-label={`revert ${label}`}
        onClick={onClick}
      >
        <IconArrowBackUp size={14} stroke={1.5} />
      </ActionIcon>
    </Tooltip>
  );
}

/** Invisible twin of the edit ActionIcon — keeps read-only row amounts aligned. */
function ActionSlotPlaceholder() {
  return (
    <ActionIcon
      color="gray"
      size="sm"
      variant="subtle"
      className={drawer.hoverRevealPencil}
      aria-hidden
      tabIndex={-1}
      style={{ visibility: "hidden", pointerEvents: "none" }}
    >
      <IconPencil size={14} stroke={1.5} />
    </ActionIcon>
  );
}

/** Base rent — overrideable like any other component (§9.6). The override is
 * Floor-Plan scoped: a quoted rent corrects the plan you are looking at, not
 * every layout at the Property. */
function RentRow({ amount, floorPlanId }: { amount: number | null; floorPlanId: string | null }) {
  const scope = floorPlanId
    ? { target_scope: "floor_plan" as const, floor_plan_id: floorPlanId }
    : {};
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const [opened, setOpened] = useState(false);
  const [value, setValue] = useState<number | "">("");
  const [note, setNote] = useState("");
  const draft = draftOverrides.get("base_rent");
  const pending = draft !== undefined;
  const shown = pending && typeof draft?.value === "number" ? draft.value : amount;

  return (
    <CostRow
      label="Base rent"
      state="actual"
      testId="cost-state-rent"
      amount={shown}
      pending={pending}
      subline={pending ? "Your edit applies when you save" : undefined}
      hoverRevealAction={!pending}
      action={
        pending ? (
          <RevertButton
            label="base rent"
            onClick={() =>
              setDraftOverride("base_rent", { value: null, note: REVERT_NOTE, ...scope })
            }
          />
        ) : (
          <Popover
            opened={opened}
            onChange={setOpened}
            hideDetached={false}
            width={240}
            position="bottom-end"
            withArrow
          >
            <Popover.Target>
              <ActionIcon
                color="gray"
                size="sm"
                variant="subtle"
                className={drawer.hoverRevealPencil}
                aria-label="edit Base rent"
                onClick={() => {
                  setValue(amount ?? "");
                  setNote("");
                  setOpened(true);
                }}
              >
                <IconPencil size={14} stroke={1.5} />
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown>
              <Stack gap="xs">
                <NumberInput
                  label="Monthly rent"
                  prefix="$"
                  min={0}
                  value={value}
                  onChange={(next) => setValue(typeof next === "number" ? next : "")}
                />
                <TextInput
                  label="Note"
                  placeholder="e.g. leasing office quote"
                  value={note}
                  onChange={(event) => setNote(event.currentTarget.value)}
                />
                <Button
                  size="xs"
                  disabled={value === ""}
                  onClick={() => {
                    if (value === "") return;
                    setDraftOverride("base_rent", {
                      value,
                      note: note.trim() || null,
                      ...scope,
                    });
                    setOpened(false);
                  }}
                >
                  Apply
                </Button>
              </Stack>
            </Popover.Dropdown>
          </Popover>
        )
      }
    />
  );
}

/** Security deposit — a Floor-Plan extraction, overrideable like base rent (§9.6). */
function SecurityDepositRow({
  amount,
  floorPlanId,
  savedOverride = false,
}: {
  amount: number | null;
  floorPlanId: string | null;
  savedOverride?: boolean;
}) {
  const scope = floorPlanId
    ? { target_scope: "floor_plan" as const, floor_plan_id: floorPlanId }
    : {};
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const [opened, setOpened] = useState(false);
  const [value, setValue] = useState<number | "">("");
  const [note, setNote] = useState("");
  const draft = draftOverrides.get("security_deposit");
  const pending = draft !== undefined;
  const shown = pending && typeof draft?.value === "number" ? draft.value : amount;
  const showRevert = pending || savedOverride;

  return (
    <CostRow
      label="Security deposit"
      state={savedOverride && !pending ? "manual" : amount == null ? "unknown" : "actual"}
      testId="cost-state-security-deposit"
      amount={shown}
      pending={pending}
      manual={savedOverride && !pending}
      icons={<StatusIcons refundable />}
      subline={pending ? "Your edit applies when you save" : undefined}
      hoverRevealAction={!showRevert}
      action={
        showRevert ? (
          <RevertButton
            label="security deposit"
            onClick={() =>
              setDraftOverride("security_deposit", { value: null, note: REVERT_NOTE, ...scope })
            }
          />
        ) : (
          <Popover
            opened={opened}
            onChange={setOpened}
            hideDetached={false}
            width={240}
            position="bottom-end"
            withArrow
          >
            <Popover.Target>
              <ActionIcon
                color="gray"
                size="sm"
                variant="subtle"
                className={drawer.hoverRevealPencil}
                aria-label="edit Security deposit"
                onClick={() => {
                  setValue(amount ?? "");
                  setNote("");
                  setOpened(true);
                }}
              >
                <IconPencil size={14} stroke={1.5} />
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown>
              <Stack gap="xs">
                <NumberInput
                  label="Security deposit"
                  prefix="$"
                  min={0}
                  value={value}
                  onChange={(next) => setValue(typeof next === "number" ? next : "")}
                />
                <TextInput
                  label="Note"
                  placeholder="e.g. leasing office quote"
                  value={note}
                  onChange={(event) => setNote(event.currentTarget.value)}
                />
                <Button
                  size="xs"
                  disabled={value === ""}
                  onClick={() => {
                    if (value === "") return;
                    setDraftOverride("security_deposit", {
                      value,
                      note: note.trim() || null,
                      ...scope,
                    });
                    setOpened(false);
                  }}
                >
                  Apply
                </Button>
              </Stack>
            </Popover.Dropdown>
          </Popover>
        )
      }
    />
  );
}

function looseFeeLabel(name: string): string {
  return name.replaceAll("_", " ");
}

function componentForUtility(composition: AllInComponents | null, utility: UtilityName) {
  if (!composition) return undefined;
  const direct = composition.components.find((component) => component.name === utility);
  if (direct) return direct;
  if (utility === "water") {
    return composition.components.find((component) => component.name === "water_sewer");
  }
  if (utility === "trash") {
    return composition.components.find((component) => component.name === "valet_trash");
  }
  return undefined;
}

function UtilityRow({
  utility,
  label,
  amountEditable,
  extractedIncluded,
  utilityOverrides,
  composition,
}: {
  utility: UtilityName;
  label: string;
  amountEditable: boolean;
  extractedIncluded: string[] | null;
  utilityOverrides: UtilityOverride[];
  composition: AllInComponents | null;
}) {
  const { draftUtilities, setDraftUtility } = useListingDetailDraft();
  const server = utilityOverrides.find((entry) => entry.utility === utility);
  const draft = draftUtilities.get(utility);
  const active = draft ?? server;
  const included = effectiveUtilitiesIncluded(
    extractedIncluded,
    utilityOverrides,
    draftUtilities,
  ).includes(utility);
  const component = componentForUtility(composition, utility);
  const displayAmount = included ? 0 : (active?.monthly_amount ?? component?.amount ?? null);
  const manuallyOverridden =
    active !== undefined && (active.included !== null || active.monthly_amount !== null);
  const [opened, setOpened] = useState(false);
  const [nextIncluded, setNextIncluded] = useState(included);
  const [amount, setAmount] = useState<number | "">("");

  const state = manuallyOverridden
    ? "manual"
    : included || component?.tag === "actual"
      ? "extracted"
      : (component?.tag ?? "unknown");

  const showRevert = manuallyOverridden || draft !== undefined;

  return (
    <CostRow
      label={label}
      state={state}
      testId={`utility-state-${utility}`}
      counted={!included}
      manual={manuallyOverridden && !draft}
      pending={draft !== undefined}
      amount={utility === "cooling" && !included ? null : displayAmount}
      amountText={utility === "cooling" && !included ? "—" : undefined}
      icons={<StatusIcons included={included} />}
      subline={
        utility === "cooling"
          ? "Cost sits inside the electricity estimate — inclusion only"
          : component?.note || undefined
      }
      hoverRevealAction={!showRevert}
      action={
        showRevert ? (
          <RevertButton
            label={`${label} utility override`}
            onClick={() =>
              setDraftUtility(utility, { included: null, monthly_amount: null, note: null })
            }
          />
        ) : (
          <Popover
            opened={opened}
            onChange={setOpened}
            hideDetached={false}
            width={250}
            position="bottom-end"
            withArrow
          >
            <Popover.Target>
              <ActionIcon
                color="gray"
                size="sm"
                variant="subtle"
                className={drawer.hoverRevealPencil}
                aria-label={`edit ${label}`}
                onClick={() => {
                  setNextIncluded(included);
                  setAmount(active?.monthly_amount ?? component?.amount ?? "");
                  setOpened(true);
                }}
              >
                <IconPencil size={14} stroke={1.5} />
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown>
              {/* Convention across every popover here: toggles, then amounts,
                  then note — the toggles decide whether the amount applies. */}
              <Stack gap="xs">
                <Checkbox
                  label="Included in rent"
                  checked={nextIncluded}
                  onChange={(event) => setNextIncluded(event.currentTarget.checked)}
                />
                {amountEditable && (
                  <NumberInput
                    label="Monthly amount"
                    description="Leave blank to use the extracted or regional estimate."
                    prefix="$"
                    min={0}
                    disabled={nextIncluded}
                    value={amount}
                    onChange={(next) => setAmount(typeof next === "number" ? next : "")}
                  />
                )}
                <Button
                  size="xs"
                  onClick={() => {
                    setDraftUtility(utility, {
                      included: nextIncluded,
                      monthly_amount:
                        nextIncluded || !amountEditable || amount === "" ? null : amount,
                      note: null,
                    });
                    setOpened(false);
                  }}
                >
                  Apply
                </Button>
              </Stack>
            </Popover.Dropdown>
          </Popover>
        )
      }
    />
  );
}

/** A checklist-slot row: monthly fees and one-time move-in charges share one
 * editor; the one-time variant adds the required / refundable / credited
 * decisions the move-in figure depends on. */
function SlotRow({
  slot,
  label,
  entry,
  monthly,
  subtitle,
  charge,
  enteredByName,
  original,
  fallbackAmount,
  fallbackState,
  uncountedReason,
}: {
  slot: string;
  label: string;
  entry: FeeEntry | undefined;
  monthly: boolean;
  subtitle?: string;
  charge?: MoveInCharge;
  enteredByName?: string;
  original?: number;
  fallbackAmount?: number | null;
  fallbackState?: string;
  /** why this charge is out of the totals — dims the row and strikes the figure */
  uncountedReason?: string;
}) {
  const { draftFees, setDraftFee } = useListingDetailDraft();
  const draftEntry = draftFees.get(slot);
  const [opened, setOpened] = useState(false);
  const [amount, setAmount] = useState<number | "">("");
  const [credited, setCredited] = useState<number | "">("");
  const [required, setRequired] = useState(true);
  const [refundable, setRefundable] = useState(false);
  const [isCredited, setIsCredited] = useState(false);

  const pending = draftEntry !== undefined;
  const state = pending ? "manual" : (entry?.value_state ?? fallbackState ?? "unknown");
  const serverAmount = entry?.amount ?? fallbackAmount ?? null;
  const displayAmount = pending ? draftEntry.amount : (charge?.amount ?? serverAmount);
  const creditedAmount = pending
    ? (draftEntry.credited_amount ?? 0)
    : (entry?.credited_amount ?? charge?.credited ?? 0);
  const effectiveRequired = pending
    ? (draftEntry.required ?? true)
    : (entry?.required ?? charge?.required ?? true);
  const effectiveRefundable = pending
    ? (draftEntry.refundable ?? null)
    : (entry?.refundable ?? charge?.refundable ?? null);
  // A caller-supplied reason (no pets in the household, say) is the machine's
  // own exclusion: the composer already leaves that charge out, so the row must
  // say so rather than implying it is in the totals. An explicit human decision
  // still wins over it.
  const explicitCounted = pending ? draftEntry.counted : entry?.counted;
  const counted =
    explicitCounted ??
    (uncountedReason !== undefined
      ? false
      : pending
        ? effectiveRequired
        : (charge?.counted ?? true));

  const reason =
    uncountedReason ??
    (counted ? undefined : monthly ? "Not counted in the all-in" : "Not required to move in");
  const attribution =
    !pending && state === "manual"
      ? `${enteredByName ?? "Someone"} entered this`
      : pending
        ? "Your edit applies when you save"
        : undefined;
  const subline = [subtitle, charge?.note, attribution, counted ? undefined : reason]
    .filter(Boolean)
    .join(" · ");

  const showRevert = pending || state === "manual";

  return (
    <CostRow
      label={label}
      state={state}
      testId={`fee-state-${slot}`}
      counted={counted}
      manual={!pending && state === "manual"}
      pending={pending}
      amount={displayAmount ?? null}
      icons={
        <StatusIcons
          refundable={monthly ? undefined : effectiveRefundable}
          credited={!monthly && creditedAmount > 0}
        />
      }
      subline={subline || undefined}
      hoverRevealAction={!showRevert}
      action={
        showRevert ? (
          <RevertButton
            label={label}
            onClick={() =>
              setDraftFee(slot, {
                amount: original ?? null,
                state: original !== undefined ? "extracted" : "unknown",
                counted: null,
                required: null,
                refundable: null,
                credited_amount: null,
              })
            }
          />
        ) : (
          <Popover
            opened={opened}
            onChange={setOpened}
            hideDetached={false}
            width={252}
            position="bottom-end"
            withArrow
          >
            <Popover.Target>
              <ActionIcon
                color="gray"
                size="sm"
                variant="subtle"
                className={drawer.hoverRevealPencil}
                aria-label={`edit ${label}`}
                onClick={() => {
                  setAmount(displayAmount ?? "");
                  setCredited(creditedAmount || "");
                  setRequired(effectiveRequired);
                  setRefundable(effectiveRefundable === true);
                  setIsCredited(creditedAmount > 0);
                  setOpened(true);
                }}
              >
                <IconPencil size={14} stroke={1.5} />
              </ActionIcon>
            </Popover.Target>
            <Popover.Dropdown>
              <Stack gap="xs">
                {monthly ? (
                  <Checkbox
                    label="Count toward all-in"
                    checked={counted}
                    onChange={(event) =>
                      setDraftFee(slot, {
                        amount: displayAmount ?? null,
                        state: entry?.value_state === "manual" ? "manual" : "extracted",
                        counted: event.currentTarget.checked,
                      })
                    }
                  />
                ) : (
                  <>
                    <Checkbox
                      label="Required to move in"
                      checked={required}
                      onChange={(event) => setRequired(event.currentTarget.checked)}
                    />
                    <Checkbox
                      label="Refundable"
                      checked={refundable}
                      onChange={(event) => setRefundable(event.currentTarget.checked)}
                    />
                    <Checkbox
                      label="Credited to first month's rent"
                      checked={isCredited}
                      onChange={(event) => setIsCredited(event.currentTarget.checked)}
                    />
                  </>
                )}
                <NumberInput
                  label={monthly ? "Monthly amount" : "One-time amount"}
                  prefix="$"
                  min={0}
                  value={amount}
                  onChange={(next) => setAmount(typeof next === "number" ? next : "")}
                />
                {!monthly && isCredited && (
                  <NumberInput
                    label="Credited amount"
                    description="Only the remainder counts as cash at move-in."
                    prefix="$"
                    min={0}
                    value={credited}
                    onChange={(next) => setCredited(typeof next === "number" ? next : "")}
                  />
                )}
                <Button
                  size="xs"
                  onClick={() => {
                    setDraftFee(slot, {
                      amount: amount === "" ? null : amount,
                      ...(monthly
                        ? {}
                        : {
                            required,
                            refundable,
                            counted: required,
                            credited_amount: isCredited && credited !== "" ? credited : null,
                          }),
                    });
                    setOpened(false);
                  }}
                >
                  Apply
                </Button>
              </Stack>
            </Popover.Dropdown>
          </Popover>
        )
      }
    />
  );
}

function SectionLabel({ children, first }: { children: ReactNode; first?: boolean }) {
  return (
    <Group justify="space-between" align="center" gap="xs" wrap="nowrap">
      <Text
        className={`${drawer.ledgerSectionLabel} ${
          first ? drawer.ledgerSectionLabelFirst : drawer.ledgerSectionLabelFollow
        }`}
      >
        {children}
      </Text>
    </Group>
  );
}

function Tile({
  label,
  value,
  sub,
  badges,
  flagged,
  action,
  kind,
}: {
  label: string;
  value: string;
  sub?: string;
  badges?: string[];
  flagged?: boolean;
  action?: ReactNode;
  kind: "monthly" | "moveIn";
}) {
  return (
    <Box
      className={classes.tile}
      data-kind={kind}
      data-flagged={flagged ? "true" : undefined}
    >
      <Group justify="space-between" wrap="nowrap" gap={4}>
        <Text className={classes.tileLabel}>{label}</Text>
        {action}
      </Group>
      <Text className={`${classes.tileValue} ${drawer.tabularNums}`}>{value}</Text>
      {sub ? (
        <Text size="xs" c="dimmed" className={drawer.tabularNums}>
          {sub}
        </Text>
      ) : null}
      {badges && badges.length > 0 && (
        <Group gap={4} mt={4}>
          <CompositionBadges badges={badges} />
        </Group>
      )}
    </Box>
  );
}

/** The all-in override lives on the monthly total (§9.6). */
function AllInOverrideAction({ overridden }: { overridden: boolean }) {
  const { draftOverrides, setDraftOverride } = useListingDetailDraft();
  const [opened, setOpened] = useState(false);
  const [amount, setAmount] = useState<number | "">("");
  const [note, setNote] = useState("");
  const draft = draftOverrides.get("all_in_monthly");
  const showRevert = overridden || draft !== undefined;

  if (showRevert) {
    return (
      <RevertButton
        label="all-in override"
        onClick={() => setDraftOverride("all_in_monthly", { value: null, note: REVERT_NOTE })}
      />
    );
  }

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      hideDetached={false}
      width={240}
      position="bottom-end"
      withArrow
    >
      <Popover.Target>
        <ActionIcon
          color="gray"
          size="sm"
          variant="subtle"
          className={drawer.hoverRevealPencil}
          aria-label="edit All-in monthly"
          onClick={() => {
            setAmount("");
            setNote("");
            setOpened(true);
          }}
        >
          <IconPencil size={14} stroke={1.5} />
        </ActionIcon>
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
              onChange={(event) => setNote(event.currentTarget.value)}
            />
            <Button
              size="xs"
              disabled={amount === ""}
              onClick={() => {
                if (amount === "") return;
                setDraftOverride("all_in_monthly", { value: amount, note: note.trim() || null });
                setOpened(false);
              }}
            >
              Apply
            </Button>
          </Stack>
        </Popover.Dropdown>
      </Popover>
  );
}

function TotalRow({
  label,
  value,
  badges,
  action,
  subtotals,
  hoverRevealAction = false,
}: {
  label: string;
  value: string;
  badges?: ReactNode;
  action?: ReactNode;
  subtotals?: ReactNode;
  hoverRevealAction?: boolean;
}) {
  return (
    <Box
      className={classes.total}
      data-hover-reveal={hoverRevealAction ? "true" : undefined}
    >
      <Group gap="sm" wrap="wrap" className={classes.totalLabel}>
        <Text size="sm" fw={700}>
          {label}
        </Text>
        {badges}
      </Group>
      <Group gap={4} wrap="nowrap" className={classes.valueAction}>
        <Text className={`${classes.totalValue} ${drawer.tabularNums}`}>{value}</Text>
        {action ?? <ActionSlotPlaceholder />}
      </Group>
      {subtotals ? <Box className={classes.subtotals}>{subtotals}</Box> : null}
    </Box>
  );
}


/**
 * Figures confirmed on a tour, offered to this Listing (VC-7, DESIGN §9.7).
 *
 * Rendered with the **staged-override presentation** an unsaved manual edit
 * already uses — the hatched row and dashed dot — because that is exactly what
 * this is: a value someone is proposing, not one the Listing holds.
 *
 * These rows are the **single sanctioned exception to the one-icon action
 * slot** (§13.2): accept and reject are both primary, and neither may hide
 * behind a hover. Everywhere else the pencil/revert slot stays single.
 */
function VisitProposalRows({
  proposals,
  huntId,
  memberNames,
  canDecide,
}: {
  proposals: VisitFeeProposal[];
  huntId: string;
  memberNames?: Map<string, string>;
  canDecide: boolean;
}) {
  const decide = useDecideFeeProposal(huntId);
  if (proposals.length === 0) return null;

  return (
    <>
      <SectionLabel>Confirmed on a visit</SectionLabel>
      {proposals.map((proposal) => {
        const who = memberNames?.get(proposal.created_by);
        return (
          <CostRow
            key={proposal.id}
            label={proposalLabel(proposal)}
            state="manual"
            testId={`proposal-${proposal.target_key}`}
            amount={Number(proposal.amount)}
            pending
            subline={
              who ? `${who} confirmed this on a tour` : "Confirmed on a tour"
            }
            action={
              canDecide ? (
                <Group gap={2} wrap="nowrap">
                  <Tooltip label="Accept — writes this to the listing">
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="sage"
                      aria-label={`accept ${proposalLabel(proposal)}`}
                      disabled={decide.isPending}
                      onClick={() =>
                        decide.mutate({
                          visitId: proposal.visit_id,
                          proposalId: proposal.id,
                          action: "accept",
                        })
                      }
                    >
                      <IconCheck size={14} stroke={1.8} />
                    </ActionIcon>
                  </Tooltip>
                  <Tooltip label="Reject — the visit keeps its own figure">
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="gray"
                      aria-label={`reject ${proposalLabel(proposal)}`}
                      disabled={decide.isPending}
                      onClick={() =>
                        decide.mutate({
                          visitId: proposal.visit_id,
                          proposalId: proposal.id,
                          action: "reject",
                        })
                      }
                    >
                      <IconX size={14} stroke={1.8} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
              ) : undefined
            }
          />
        );
      })}
    </>
  );
}

/** A proposal's row label, in the vocabulary the rest of the section uses. */
export function proposalLabel(proposal: VisitFeeProposal): string {
  if (proposal.target === "override") {
    return proposal.target_key === "base_rent" ? "Base rent" : "All-in monthly";
  }
  return (
    FEE_SLOTS.find((entry) => entry.slot === proposal.target_key)?.label ??
    proposal.target_key.replaceAll("_", " ")
  );
}

export function CostAndFees({
  composition,
  moveIn = null,
  fees,
  oneTimeFees = [],
  household,
  memberNames,
  members,
  feeOriginals,
  extractedIncluded = null,
  utilityOverrides = [],
  allInOverridden = false,
  securityDepositOverridden = false,
  floorPlanId = null,
  proposals = [],
  huntId = "",
  canDecideProposals = false,
}: {
  composition: AllInComponents | null;
  moveIn?: MoveInComponents | null;
  fees: FeeEntry[];
  oneTimeFees?: OneTimeFee[];
  household?: Household;
  memberNames?: Map<string, string>;
  members?: HuntMember[];
  feeOriginals?: Map<string, number>;
  extractedIncluded?: string[] | null;
  utilityOverrides?: UtilityOverride[];
  allInOverridden?: boolean;
  securityDepositOverridden?: boolean;
  floorPlanId?: string | null;
  /** Pending Fee Proposals addressed to this Listing (VC-7). */
  proposals?: VisitFeeProposal[];
  huntId?: string;
  /** Deciding is a cost write, so it follows the Override permission (§4.2). */
  canDecideProposals?: boolean;
}) {
  const { draftUtilities } = useListingDetailDraft();
  const bySlot = new Map(fees.map((entry) => [entry.fee_slot, entry]));
  const chargeByName = new Map((moveIn?.charges ?? []).map((charge) => [charge.name, charge]));
  const pets = (household?.cats ?? 0) + (household?.dogs ?? 0);
  const nameFor = (entry: FeeEntry | undefined) => {
    if (!entry?.entered_by) return undefined;
    return (
      memberNames?.get(entry.entered_by) ??
      (members ? memberDisplayName(members, entry.entered_by) : undefined) ??
      "Member"
    );
  };

  const rent = composition?.components.find((component) => component.name === "rent");
  const utilityNames = new Set([
    ...UTILITY_ROWS.map((row) => row.utility),
    "water_sewer",
    "valet_trash",
    "rent",
    "pet rent",
  ]);
  const monthlySlotIds = new Set(MONTHLY_FEE_SLOTS.map((entry) => entry.slot));
  // Unmapped mandatory fees compose under their page name; slotted fees edit via
  // the checklist rows below — showing both would duplicate the same charge.
  const looseFees = (composition?.components ?? []).filter(
    (component) => !utilityNames.has(component.name) && !monthlySlotIds.has(component.name),
  );
  const included = effectiveUtilitiesIncluded(extractedIncluded, utilityOverrides, draftUtilities);
  const inclusionLevel = included.some((utility) => MAJOR_UTILITIES.has(utility))
    ? "highest"
    : included.length > 0
      ? "high"
      : "none";

  return (
    <Stack gap={0}>
      <Box className={classes.tiles}>
        <Tile
          kind="monthly"
          label="All-in / month"
          value={composition?.total == null ? "unknown" : money(composition.total)}
          sub={
            composition
              ? [
                  rent?.amount != null ? `${money(rent.amount)} rent` : null,
                  composition.estimated_total > 0
                    ? `~${money(composition.estimated_total)} estimated`
                    : null,
                  composition.overridden ? "overridden" : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : undefined
          }
          badges={composition?.badges}
        />
        <Tile
          kind="moveIn"
          label="Cash at move-in"
          value={
            moveIn == null
              ? "—"
              : `${money(moveIn.total ?? moveIn.subtotal)}${moveIn.incomplete ? "+" : ""}`
          }
          sub={
            moveIn
              ? [
                  `${money(moveIn.refundable_total)} refundable`,
                  `${money(moveIn.non_refundable_total)} not`,
                  moveIn.unclassified_total > 0
                    ? `${money(moveIn.unclassified_total)} unclassified`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")
              : undefined
          }
          flagged={moveIn?.incomplete}
          badges={moveIn?.incomplete ? ["move_in_incomplete"] : []}
        />
      </Box>

      {composition === null ? (
        <Text size="sm" c="dimmed" mt="sm">
          No composition yet — ingestion may still be running.
        </Text>
      ) : (
        <>
          <VisitProposalRows
            proposals={proposals}
            huntId={huntId}
            memberNames={memberNames}
            canDecide={canDecideProposals}
          />
          <SectionLabel first>Monthly</SectionLabel>
          <RentRow amount={rent?.amount ?? null} floorPlanId={floorPlanId} />
          {looseFees.map((component) => (
            <SlotRow
              key={component.name}
              slot={component.name}
              label={looseFeeLabel(component.name)}
              entry={bySlot.get(component.name)}
              monthly
              fallbackAmount={component.amount}
              fallbackState={component.tag}
              subtitle={component.note || undefined}
              enteredByName={nameFor(bySlot.get(component.name))}
              original={feeOriginals?.get(component.name)}
            />
          ))}
          {MONTHLY_FEE_SLOTS.map(({ slot, label }) => {
            const petSlot = slot.startsWith("pet_rent");
            return (
              <SlotRow
                key={slot}
                slot={slot}
                label={label}
                entry={bySlot.get(slot)}
                monthly
                enteredByName={nameFor(bySlot.get(slot))}
                original={feeOriginals?.get(slot)}
                uncountedReason={
                  petSlot && pets === 0 ? "Not counted — no pets in this hunt's household" : undefined
                }
              />
            );
          })}

          <SectionLabel>
            Utilities
            {included.length > 0 ? (
              <Text component="span" className={classes.included} data-level={inclusionLevel}>
                {" "}
                · included: {included.join(" · ")}
              </Text>
            ) : (
              <Text component="span" className={classes.included} data-level="none">
                {" "}
                · none included
              </Text>
            )}
          </SectionLabel>
          {UTILITY_ROWS.map((row) => (
            <UtilityRow
              key={row.utility}
              {...row}
              extractedIncluded={extractedIncluded}
              utilityOverrides={utilityOverrides}
              composition={composition}
            />
          ))}

          <TotalRow
            label="All-in / month"
            value={composition.total == null ? "unknown" : money(composition.total)}
            badges={
              composition.overridden ? (
                <Badge size="xs" color="manual" variant="light">
                  override
                </Badge>
              ) : null
            }
            action={<AllInOverrideAction overridden={allInOverridden} />}
            hoverRevealAction={!allInOverridden}
          />
        </>
      )}

      <SectionLabel>Move-in &amp; one-time</SectionLabel>
      {moveIn && (
        <>
          {moveIn.charges
            .filter((charge) => charge.name === "first_month")
            .map((charge) => (
              <CostRow
                key={charge.name}
                label={MOVE_IN_LINE_LABELS[charge.name] ?? charge.name}
                state={charge.tag}
                amount={charge.amount}
                counted={charge.counted}
                icons={<StatusIcons refundable={charge.refundable} />}
                subline={charge.note || undefined}
              />
            ))}
          {moveIn.charges
            .filter((charge) => charge.name === "security_deposit")
            .map((charge) => (
              <SecurityDepositRow
                key={charge.name}
                amount={charge.amount}
                floorPlanId={floorPlanId}
                savedOverride={securityDepositOverridden}
              />
            ))}
        </>
      )}
      {ONE_TIME_FEE_SLOTS.map(({ slot, label }) => {
        const extracted = feeForSlot(oneTimeFees, slot);
        const petSlot = slot.startsWith("pet_");
        return (
          <SlotRow
            key={slot}
            slot={slot}
            label={label}
            entry={bySlot.get(slot)}
            charge={chargeByName.get(slot)}
            monthly={false}
            subtitle={extracted ? basisLabel(extracted) || undefined : undefined}
            enteredByName={nameFor(bySlot.get(slot))}
            original={feeOriginals?.get(slot)}
            uncountedReason={
              petSlot && pets === 0 ? "Not required — no pets in this hunt's household" : undefined
            }
          />
        );
      })}
      {(moveIn?.charges ?? [])
        .filter(
          (charge) =>
            !["first_month", "security_deposit"].includes(charge.name) &&
            !ONE_TIME_FEE_SLOTS.some((entry) => entry.slot === charge.name),
        )
        .map((charge) => (
          <CostRow
            key={charge.name}
            label={charge.name}
            state={charge.tag}
            amount={charge.amount}
            counted={charge.counted}
            icons={
              <StatusIcons
                refundable={charge.refundable}
                credited={(charge.credited ?? 0) > 0}
              />
            }
            subline={charge.note || undefined}
          />
        ))}

      {moveIn && (
        <TotalRow
          label="Cash at move-in"
          value={`${money(moveIn.total ?? moveIn.subtotal)}${moveIn.incomplete ? "+" : ""}`}
          badges={moveIn.incomplete ? <CompositionBadges badges={["move_in_incomplete"]} /> : null}
          subtotals={
            <Group gap="md">
              <Text size="xs" c="dimmed">
                Refundable <b>{money(moveIn.refundable_total)}</b>
              </Text>
              <Text size="xs" c="dimmed">
                Non-refundable <b>{money(moveIn.non_refundable_total)}</b>
              </Text>
              {moveIn.unclassified_total > 0 && (
                <Text size="xs" c="dimmed">
                  Refundability unstated <b>{money(moveIn.unclassified_total)}</b>
                </Text>
              )}
            </Group>
          }
        />
      )}
      {moveIn?.incomplete && (
        <Text size="xs" c="dimmed" mt={6}>
          A required charge has no stated amount, so this is a known subtotal — not a total. The
          move-in cost criterion stays unknown until it is filled in.
        </Text>
      )}

      <Group gap="md" mt="sm" className={classes.legend}>
        {[
          ["actual", "from the listing"],
          ["estimated", "estimated"],
          ["manual", "entered by a person"],
          ["unknown", "unknown"],
        ].map(([state, label]) => (
          <Group gap={5} wrap="nowrap" key={state}>
            <Box component="span" className={`${drawer.stateDot} ${STATE_CLASS[state]}`} />
            <Text size="xs" c="dimmed">
              {label}
            </Text>
          </Group>
        ))}
      </Group>
      <Group gap="md" mt={4} className={classes.legend}>
        <Group gap={5} wrap="nowrap">
          <Box component="span" className={classes.icon} data-tone="refundable">
            <IconCashBanknote size={14} stroke={1.7} />
          </Box>
          <Text size="xs" c="dimmed">
            refundable
          </Text>
        </Group>
        <Group gap={5} wrap="nowrap">
          <Box component="span" className={classes.icon} data-tone="nonRefundable">
            <IconCashBanknoteOff size={14} stroke={1.7} />
          </Box>
          <Text size="xs" c="dimmed">
            non-refundable
          </Text>
        </Group>
        <Group gap={5} wrap="nowrap">
          <Box component="span" className={classes.icon} data-tone="credited">
            <IconCashBanknoteMoveBack size={14} stroke={1.7} />
          </Box>
          <Text size="xs" c="dimmed">
            credited to rent
          </Text>
        </Group>
        <Group gap={5} wrap="nowrap">
          <Box component="span" className={classes.icon} data-tone="included">
            <IconCircleCheck size={13} stroke={1.7} />
          </Box>
          <Text size="xs" c="dimmed">
            included in rent
          </Text>
        </Group>
      </Group>
    </Stack>
  );
}
