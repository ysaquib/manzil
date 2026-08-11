// Answer forks, surfaced for a human (VC-6, plan §7.2).
//
// Two people answered the same item and one of them was offline. Both writes
// landed — the table is append-only and nothing is ever discarded — so the only
// open question is which value the checklist should show. The app does not
// guess: last-write-wins would silently overwrite whichever member happened to
// walk into a signal dead spot, which is exactly the person whose answer was
// hardest to collect.
//
// This reuses the **dispute checkpoint** vocabulary P3-6 established rather
// than inventing a second conflict idiom: both values, who and when, and one
// deliberate choice.
import { Alert, Badge, Button, Card, Group, Radio, Stack, Text } from "@mantine/core";
import { IconGitMerge } from "@tabler/icons-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import { useState } from "react";

import type { HuntContributor, HuntMember } from "../collaboration/api";
import { contributorColor, contributorDisplayName } from "../collaboration/memberDisplay";
import type { VisitEntryConflict, VisitItem, VisitUnit } from "./types";

dayjs.extend(relativeTime);

/** Branches of one fork, in the order they landed. */
export interface Fork {
  parentId: string;
  branches: VisitEntryConflict[];
}

/** Group flat conflict rows into one fork per contested answer. */
export function groupForks(conflicts: VisitEntryConflict[]): Fork[] {
  const byParent = new Map<string, VisitEntryConflict[]>();
  for (const conflict of conflicts) {
    const bucket = byParent.get(conflict.fork_parent_id);
    if (bucket) bucket.push(conflict);
    else byParent.set(conflict.fork_parent_id, [conflict]);
  }
  return [...byParent.entries()].map(([parentId, branches]) => ({
    parentId,
    branches: [...branches].sort((a, b) => a.created_at.localeCompare(b.created_at)),
  }));
}

/**
 * How a branch's answer reads in the picker.
 *
 * A cleared answer is a real choice — the tombstone that means "nobody has
 * looked" — so it says so rather than rendering as a blank row.
 */
export function branchValueLabel(branch: VisitEntryConflict): string {
  if (branch.answer_text) return branch.answer_text;
  const { value } = branch;
  if (value === null || value === undefined) return "Cleared";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") {
    // A Check stores "ok"/"problem" but reads as "Fine"/"Problem" on the
    // control (VisitControls). The picker has to use the same words the tour
    // used, or the reader is choosing between an answer and a synonym.
    if (value === "ok") return "Fine";
    if (value === "problem") return "Problem";
    return value;
  }
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function authorName(
  contributors: (HuntContributor | HuntMember)[],
  userId: string,
  viewerId: string | null,
): string {
  if (userId === viewerId) return "You";
  return contributorDisplayName(
    contributors.find((contributor) => contributor.user_id === userId),
  );
}

function ForkCard({
  fork,
  items,
  units,
  contributors,
  viewerId,
  onResolve,
  busy,
}: {
  fork: Fork;
  items: VisitItem[];
  units: VisitUnit[];
  contributors: (HuntContributor | HuntMember)[];
  viewerId: string | null;
  onResolve: (branch: VisitEntryConflict) => void;
  busy: boolean;
}) {
  const first = fork.branches[0]!;
  // Newest branch preselected: it is what the checklist is currently showing,
  // so the default choice changes nothing until the reader decides otherwise.
  const newest = fork.branches[fork.branches.length - 1]!;
  const [chosen, setChosen] = useState(newest.id);

  const item = items.find((candidate) => candidate.key === first.item_key);
  const unit = units.find((candidate) => candidate.id === first.visit_unit_id);

  return (
    <Card withBorder padding="sm" radius="sm">
      <Stack gap="xs">
        <Group gap={6} wrap="wrap">
          <Text size="sm" fw={600}>
            {item?.label ?? first.item_key}
          </Text>
          <Badge size="xs" variant="light" color="gray" radius="sm">
            {unit ? unit.label : "Whole property"}
          </Badge>
        </Group>

        <Radio.Group value={chosen} onChange={setChosen}>
          <Stack gap={6}>
            {fork.branches.map((branch) => (
              <Radio
                key={branch.id}
                value={branch.id}
                disabled={busy}
                label={
                  <Group gap={6} wrap="wrap">
                    <Text size="sm">{branchValueLabel(branch)}</Text>
                    <Group gap={4} wrap="nowrap">
                      <span
                        aria-hidden
                        style={{
                          width: 7,
                          height: 7,
                          borderRadius: "50%",
                          display: "inline-block",
                          backgroundColor: contributorColor(
                            contributors.find(
                              (contributor) => contributor.user_id === branch.author_user_id,
                            ),
                          ),
                        }}
                      />
                      <Text size="xs" c="dimmed">
                        {authorName(contributors, branch.author_user_id, viewerId)} ·{" "}
                        {dayjs(branch.created_at).fromNow()}
                      </Text>
                    </Group>
                  </Group>
                }
              />
            ))}
          </Stack>
        </Radio.Group>

        <Group justify="flex-end">
          <Button
            size="xs"
            loading={busy}
            onClick={() => {
              const branch = fork.branches.find((candidate) => candidate.id === chosen);
              if (branch) onResolve(branch);
            }}
          >
            Keep this answer
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

/**
 * The conflict surface. Renders nothing when there is nothing contested —
 * which is almost always.
 */
export function ConflictPicker({
  conflicts,
  items,
  units,
  contributors,
  members,
  viewerId,
  onResolve,
  busy = false,
}: {
  conflicts: VisitEntryConflict[];
  items: VisitItem[];
  units: VisitUnit[];
  contributors?: (HuntContributor | HuntMember)[];
  /** @deprecated Pass contributors so retained work can include former members. */
  members?: HuntMember[];
  viewerId: string | null;
  onResolve: (branch: VisitEntryConflict) => void;
  busy?: boolean;
}) {
  const identities = contributors ?? members ?? [];
  const forks = groupForks(conflicts);
  if (forks.length === 0) return null;

  return (
    <Alert
      variant="light"
      color="ochre"
      icon={<IconGitMerge size={18} />}
      title={
        forks.length === 1 ? "One answer needs a decision" : `${forks.length} answers need a decision`
      }
    >
      <Stack gap="sm">
        <Text size="sm">
          These were answered twice while someone was offline. Both are saved — pick the one the
          checklist should show.
        </Text>
        {forks.map((fork) => (
          <ForkCard
            key={fork.parentId}
            fork={fork}
            items={items}
            units={units}
            contributors={identities}
            viewerId={viewerId}
            onResolve={onResolve}
            busy={busy}
          />
        ))}
      </Stack>
    </Alert>
  );
}
