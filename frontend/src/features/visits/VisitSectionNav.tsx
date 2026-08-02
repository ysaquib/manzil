// Section navigation (VC-13).
//
// The shipped version rendered all 21 sections as a horizontal strip of chips.
// On a phone that made every section change a scrub past everything else, and
// on a desktop it wasted the width it was fighting for. Three pieces replace it,
// and they share one model:
//
//   * a **phase bar** — five items, which fit in a row on the narrowest phone,
//     each showing a dot per section so an untouched phase looks different from
//     a finished one;
//   * a **section header** that is itself the button, opening a picker listing
//     every section with its state. That is where the full 21 belongs: a list
//     you open deliberately, not a strip in the way of the thing under it;
//   * **previous / next**, because nobody tours a flat by jumping — the common
//     path is the template's own order.
//
// On a desktop the same model renders as a vertical rail (`SectionRail`), so
// the phone layout is the desktop layout with a column removed rather than a
// separate design.
import { Badge, Box, Group, Modal, Progress, ScrollArea, Stack, Text } from "@mantine/core";
import { IconChevronDown, IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { useState } from "react";

import { toneFor } from "./statusColors";
import { phasesPresent, sectionTitle, type TemplateSection } from "./visitState";
import classes from "./VisitSectionNav.module.css";

/** How much of a section is answered — the one number every surface here shows. */
export interface SectionProgress {
  answered: number;
  total: number;
}

export type SectionStatus = "empty" | "partial" | "complete";

export function statusOf(progress: SectionProgress): SectionStatus {
  if (progress.total > 0 && progress.answered >= progress.total) return "complete";
  return progress.answered > 0 ? "partial" : "empty";
}

interface NavProps<T extends TemplateSection> {
  sections: T[];
  current: string | null;
  onSelect: (key: string) => void;
  progressFor: (section: T) => SectionProgress;
}

// ---------------------------------------------------------------------------
// Phase bar — the only permanent navigation on a phone
// ---------------------------------------------------------------------------

export function PhaseBar<T extends TemplateSection>({
  sections,
  current,
  onSelect,
  progressFor,
}: NavProps<T>) {
  const groups = phasesPresent(sections);
  const activePhase = groups.find((group) =>
    group.sections.some((section) => section.key === current),
  );

  return (
    <Group gap={0} className={classes.phaseBar} role="tablist" aria-label="Checklist phases">
      {groups.map((group) => {
        const active = group.phase.key === activePhase?.phase.key;
        return (
          <button
            key={group.phase.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={classes.phaseTab}
            data-active={active || undefined}
            // Entering a phase lands on its first section, which is the one the
            // template puts first for a reason.
            onClick={() => onSelect(group.sections[0].key)}
          >
            <span className={classes.phaseName}>{group.phase.title}</span>
            <span className={classes.phaseDots} aria-hidden>
              {group.sections.map((section) => (
                <i key={section.key} data-status={statusOf(progressFor(section))} />
              ))}
            </span>
          </button>
        );
      })}
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Section header + picker
// ---------------------------------------------------------------------------

export function SectionPicker<T extends TemplateSection>({
  sections,
  current,
  onSelect,
  progressFor,
}: NavProps<T>) {
  const [open, setOpen] = useState(false);
  const active = sections.find((section) => section.key === current);
  const activeProgress = active ? progressFor(active) : null;
  const groups = phasesPresent(sections);

  return (
    <>
      <button
        type="button"
        className={classes.sectionHead}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span className={classes.sectionName}>
          {active ? sectionTitle(active.key) : "Pick a section"}
        </span>
        {activeProgress && (
          <span className={classes.sectionCount}>
            {activeProgress.answered} of {activeProgress.total}
          </span>
        )}
        <IconChevronDown size={15} aria-hidden />
      </button>

      <Modal
        opened={open}
        onClose={() => setOpen(false)}
        title="Jump to a section"
        size="md"
        scrollAreaComponent={ScrollArea.Autosize}
      >
        <Stack gap={2}>
          {groups.map((group) => (
            <Box key={group.phase.key}>
              <Text className={classes.groupLabel}>{group.phase.title}</Text>
              {group.sections.map((section) => {
                const progress = progressFor(section);
                const status = statusOf(progress);
                return (
                  <button
                    key={section.key}
                    type="button"
                    className={classes.pickerRow}
                    aria-current={section.key === current}
                    onClick={() => {
                      onSelect(section.key);
                      setOpen(false);
                    }}
                  >
                    <span className={classes.statusDot} data-status={status} aria-hidden />
                    <span className={classes.pickerName}>{sectionTitle(section.key)}</span>
                    <span className={classes.pickerCount}>
                      {progress.answered}/{progress.total}
                    </span>
                  </button>
                );
              })}
            </Box>
          ))}
        </Stack>
      </Modal>
    </>
  );
}

// ---------------------------------------------------------------------------
// Desktop rail — the same model, one column over
// ---------------------------------------------------------------------------

export function SectionRail<T extends TemplateSection>({
  sections,
  current,
  onSelect,
  progressFor,
}: NavProps<T>) {
  const groups = phasesPresent(sections);
  return (
    <nav className={classes.rail} aria-label="Sections">
      {groups.map((group) => (
        <Box key={group.phase.key}>
          <Text className={classes.groupLabel}>{group.phase.title}</Text>
          {group.sections.map((section) => {
            const progress = progressFor(section);
            return (
              <button
                key={section.key}
                type="button"
                className={classes.railRow}
                aria-current={section.key === current}
                onClick={() => onSelect(section.key)}
              >
                <span
                  className={classes.statusDot}
                  data-status={statusOf(progress)}
                  aria-hidden
                />
                <span className={classes.pickerName}>{sectionTitle(section.key)}</span>
                <span className={classes.pickerCount}>
                  {progress.answered}/{progress.total}
                </span>
              </button>
            );
          })}
        </Box>
      ))}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Previous / next
// ---------------------------------------------------------------------------

export function SectionSteps({
  previous,
  next,
  onSelect,
}: {
  previous: string | null;
  next: string | null;
  onSelect: (key: string) => void;
}) {
  if (!previous && !next) return null;
  return (
    <Group gap="sm" grow align="stretch" wrap="nowrap">
      <button
        type="button"
        className={classes.step}
        disabled={!previous}
        onClick={() => previous && onSelect(previous)}
      >
        <span className={classes.stepDir}>
          <IconChevronLeft size={12} aria-hidden /> Previous
        </span>
        <span className={classes.stepName}>{previous ? sectionTitle(previous) : "—"}</span>
      </button>
      <button
        type="button"
        className={`${classes.step} ${classes.stepNext}`}
        disabled={!next}
        onClick={() => next && onSelect(next)}
      >
        <span className={classes.stepDir}>
          Next <IconChevronRight size={12} aria-hidden />
        </span>
        <span className={classes.stepName}>{next ? sectionTitle(next) : "—"}</span>
      </button>
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Section heading inside the content pane
// ---------------------------------------------------------------------------

export function SectionHeading({
  title,
  scopeLabel,
  progress,
  /**
   * False when the compact nav is up: its header already names the section
   * directly above this card, and printing it twice in two type sizes reads as
   * a bug rather than as emphasis.
   */
  showTitle = true,
}: {
  title: string;
  scopeLabel: string;
  progress: SectionProgress;
  showTitle?: boolean;
}) {
  const status = statusOf(progress);
  const tone = toneFor(status === "complete" ? "complete" : status === "partial" ? "partial" : "empty");
  return (
    <Stack gap={6}>
      <Group
        justify={showTitle ? "space-between" : "flex-end"}
        align="center"
        wrap="wrap"
        gap="xs"
      >
        {showTitle && (
          <Text fw={600} ff="var(--mantine-font-family-headings)" size="md">
            {title}
          </Text>
        )}
        <Group gap={6} wrap="nowrap">
          <Badge variant={tone.variant} color={tone.color} radius="sm">
            {progress.answered} of {progress.total}
          </Badge>
          <Badge variant="light" color="gray" radius="sm">
            {scopeLabel}
          </Badge>
        </Group>
      </Group>
      <Progress
        size="xs"
        aria-label={`${title} progress`}
        value={(progress.answered / Math.max(progress.total, 1)) * 100}
      />
    </Stack>
  );
}
