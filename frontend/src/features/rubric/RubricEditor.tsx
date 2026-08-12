// Single-page rubric editor (§13.2): all criteria on one scrollable page with
// save-time validation. Replaces the former 3-step Stepper wizard.
import {
  Alert,
  Button,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { IconDeviceFloppy, IconPlus } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { useCallback, useMemo, useRef, useState } from "react";

import { PageHeader } from "../../components/PageHeader";
import { SettingsSaveBar } from "../../components/SettingsShell";
import { ApiError } from "../../lib/apiClient";
import type { CatalogEntry, CustomCriterionDef, RubricCriterion } from "./api";
import { usePutRubric } from "./api";
import { CustomCriterionModal } from "./CustomCriterionModal";
import { criterionKey, customCatalogEntry } from "./customCriterion";
import { CriterionCard } from "./CriterionCard";
import { CriterionGroupHeader } from "./CriterionGroupHeader";
import { CriterionPicker } from "./CriterionPicker";
import { groupCatalog } from "./catalogGroups";
import {
  type CriterionIssue,
  draftToPayload,
  initDraft,
  isCriterionDirty,
  overlapWarnings,
  validateDraft,
} from "./rubricDraft";

function isDirty(
  draft: RubricCriterion[],
  catalog: CatalogEntry[],
  saved: RubricCriterion[],
): boolean {
  const baseline = draftToPayload(initDraft(catalog, saved));
  return JSON.stringify(draftToPayload(draft)) !== JSON.stringify(baseline);
}

function labelFor(criterion: RubricCriterion, catalogLabelByKey: Map<string, string>): string {
  if (criterion.custom_def) return criterion.custom_def.label;
  return catalogLabelByKey.get(criterion.catalog_key ?? "") ?? criterionKey(criterion) ?? "Criterion";
}

export function RubricEditor({
  huntId,
  catalog,
  saved,
  onDone,
}: {
  huntId: string;
  catalog: CatalogEntry[];
  saved: RubricCriterion[];
  onDone: () => void;
}) {
  const putRubric = usePutRubric(huntId);
  const [draft, setDraft] = useState<RubricCriterion[]>(() => initDraft(catalog, saved));
  const [discardOpen, setDiscardOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  // Validated only on Save (perf + UX — see UI Decision Log): stale until the
  // next Save attempt rather than recomputed on every keystroke.
  const [saveIssues, setSaveIssues] = useState<CriterionIssue[]>([]);

  // Same object per unedited custom_def across renders, so an untouched
  // custom card's `entry` prop stays referentially stable for React.memo.
  const customEntryCache = useRef(new WeakMap<CustomCriterionDef, CatalogEntry>()).current;
  const entryForCustomDef = useCallback(
    (def: CustomCriterionDef): CatalogEntry => {
      let cached = customEntryCache.get(def);
      if (!cached) {
        cached = customCatalogEntry(def);
        customEntryCache.set(def, cached);
      }
      return cached;
    },
    [customEntryCache],
  );

  const groups = useMemo(() => groupCatalog(catalog), [catalog]);
  const catalogLabelByKey = useMemo(
    () => new Map(catalog.map((entry) => [entry.key, entry.label])),
    [catalog],
  );
  // What's actually saved right now, keyed the same way the draft is — the
  // per-card "Modified" badge/revert and the sticky bar's dirty list both
  // diff against this rather than the catalog defaults.
  const baseline = useMemo(() => initDraft(catalog, saved), [catalog, saved]);
  const baselineByKey = useMemo(() => {
    const map = new Map<string, RubricCriterion>();
    for (const criterion of baseline) {
      const key = criterionKey(criterion);
      if (key !== null) map.set(key, criterion);
    }
    return map;
  }, [baseline]);

  const customCriteria = draft.filter(
    (criterion): criterion is RubricCriterion & { custom_def: CustomCriterionDef } =>
      criterion.custom_def !== null,
  );
  const customEntries = customCriteria.map((criterion) => entryForCustomDef(criterion.custom_def));
  const entryByKey = new Map([...catalog, ...customEntries].map((e) => [e.key, e]));
  const warnings = overlapWarnings(draft, catalog);
  const infoWarnings = warnings.filter((warning) => warning.tone === "info");
  const reviewWarnings = warnings.filter((warning) => warning.tone !== "info");
  const enabledCount = draft.filter((c) => c.enabled).length;
  const criterionByKey = new Map(
    draft
      .map((criterion) => [criterionKey(criterion), criterion] as const)
      .filter((entry): entry is readonly [string, RubricCriterion] => entry[0] !== null),
  );

  const issuesByKey = useMemo(() => {
    const map = new Map<string, CriterionIssue[]>();
    for (const issue of saveIssues) {
      const list = map.get(issue.catalogKey);
      if (list) list.push(issue);
      else map.set(issue.catalogKey, [issue]);
    }
    return map;
  }, [saveIssues]);

  const dirtyByKey = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const criterion of draft) {
      const key = criterionKey(criterion);
      if (key === null) continue;
      const base = baselineByKey.get(key);
      map.set(key, base ? isCriterionDirty(criterion, base) : true);
    }
    return map;
  }, [draft, baselineByKey]);

  const dirtyLabels = useMemo(() => {
    const draftKeys = new Set<string>();
    const labels: string[] = [];
    for (const criterion of draft) {
      const key = criterionKey(criterion);
      if (key === null) continue;
      draftKeys.add(key);
      if (dirtyByKey.get(key)) labels.push(labelFor(criterion, catalogLabelByKey));
    }
    for (const criterion of baseline) {
      const key = criterionKey(criterion);
      if (key !== null && !draftKeys.has(key)) {
        labels.push(`${labelFor(criterion, catalogLabelByKey)} (removed)`);
      }
    }
    return labels;
  }, [draft, baseline, dirtyByKey, catalogLabelByKey]);

  // Stable across renders — every CriterionCard shares one instance, so an
  // untouched card's `onChange` prop never breaks React.memo.
  const setCriterion = useCallback((next: RubricCriterion) => {
    setDraft((prev) =>
      prev.map((criterion) => (criterionKey(criterion) === criterionKey(next) ? next : criterion)),
    );
  }, []);

  const removeCriterion = useCallback((key: string) => {
    setDraft((current) => current.filter((item) => criterionKey(item) !== key));
  }, []);

  const revertCriterion = useCallback(
    (key: string) => {
      const base = baselineByKey.get(key);
      setDraft((current) =>
        base
          ? current.map((item) => (criterionKey(item) === key ? base : item))
          : current.filter((item) => criterionKey(item) !== key),
      );
    },
    [baselineByKey],
  );

  const save = () =>
    putRubric.mutate(draftToPayload(draft), {
      onSuccess: ({ backfillCount }) => {
        notifications.show({
          title: backfillCount > 0 ? `Backfilling ${backfillCount} Listings` : "Rubric saved",
          message:
            backfillCount > 0
              ? "Cached evidence is updating their scores. Follow progress in Tasks."
              : "Every listing re-scores in the background.",
          color: backfillCount > 0 ? "violet" : "green",
        });
        onDone();
      },
      onError: (error) =>
        notifications.show({
          title: "Couldn't save rubric",
          message: error instanceof ApiError ? error.message : "Unexpected error",
          color: "red",
        }),
    });

  const attemptSave = () => {
    const nextIssues = validateDraft(draft, catalog);
    setSaveIssues(nextIssues);
    if (nextIssues.length > 0) {
      notifications.show({
        title: nextIssues.length === 1 ? "1 issue to fix" : `${nextIssues.length} issues to fix`,
        message: "Review the highlighted criteria before saving.",
        color: "red",
      });
      return;
    }
    save();
  };

  const cancel = () => {
    if (isDirty(draft, catalog, saved)) setDiscardOpen(true);
    else onDone();
  };

  return (
    <Stack gap="lg">
      <PageHeader
        title="Rubric"
        description="Define how listings are scored in this hunt"
        rightSlot={
          <Group gap="sm">
            <Button variant="default" onClick={cancel}>
              Cancel
            </Button>
            <Button
              leftSection={<IconDeviceFloppy size={16} stroke={1.5} />}
              onClick={attemptSave}
              disabled={enabledCount === 0}
              loading={putRubric.isPending}
            >
              Save rubric
            </Button>
          </Group>
        }
      />

      <Text size="sm" c="dimmed">
        {enabledCount} of {draft.length} criteria enabled
      </Text>

      {saveIssues.length > 0 && (
        <Alert color={"red"} title="Fix before saving">
          <Stack gap={4}>
            {saveIssues.map((issue, i) => (
              <Text size="sm" key={i}>
                {entryByKey.get(issue.catalogKey)?.label ?? issue.catalogKey}: {issue.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {infoWarnings.length > 0 && (
        <Alert color="blue" title="Option ordering">
          <Stack gap={4}>
            {infoWarnings.map((warning, i) => (
              <Text size="sm" key={i}>
                {warning.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {reviewWarnings.length > 0 && (
        <Alert color="yellow" title="Review overlapping options">
          <Stack gap={4}>
            {reviewWarnings.map((warning, i) => (
              <Text size="sm" key={i}>
                {entryByKey.get(warning.catalogKey)?.label ?? warning.catalogKey}: {warning.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      {groups.map((group) => {
        // Scored criteria get cards; the rest collapse into one add-pill strip,
        // so a category you aren't using costs a heading and a line rather than
        // a dozen empty boxes (UI Decision Log 2026-07-25).
        const scored = group.entries.filter((entry) => criterionByKey.get(entry.key)?.enabled);
        const unscored = group.entries.filter((entry) => !criterionByKey.get(entry.key)?.enabled);
        return (
          <Stack gap="sm" key={group.category}>
            <CriterionGroupHeader
              label={group.label}
              category={group.category}
              count={`${scored.length} of ${group.entries.length}`}
            />
            {/* Column count is a width budget, not a density preference: an
                edit row needs op + value + points + actions on one line, and a
                second column at `md` (~350px per card) is narrower than the
                phone case the card's own mobile branch exists to fix — and a
                media query on the card can't see it. Splitting starts at `lg`,
                where each card still clears 500px. (2026-08-11.) */}
            <SimpleGrid
              cols={{ base: 1, lg: 2, xl: 3 }}
              spacing="md"
              style={{ alignItems: "start" }}
            >
              {scored.map((entry) => {
                const criterion = criterionByKey.get(entry.key);
                return criterion ? (
                  <CriterionCard
                    key={entry.key}
                    criterion={criterion}
                    entry={entry}
                    issues={issuesByKey.get(entry.key)}
                    dirty={dirtyByKey.get(entry.key) ?? false}
                    onChange={setCriterion}
                    onRevert={revertCriterion}
                  />
                ) : null;
              })}
            </SimpleGrid>
            <CriterionPicker
              entries={unscored}
              onEnable={(entry) => {
                const criterion = criterionByKey.get(entry.key);
                if (criterion) setCriterion({ ...criterion, enabled: true });
              }}
            />
          </Stack>
        );
      })}

      <Stack gap="sm">
        <CriterionGroupHeader
          label="Custom"
          category="custom"
          count={`${customCriteria.filter((criterion) => criterion.enabled).length} scored`}
        />
        <SimpleGrid
          cols={{ base: 1, lg: 2, xl: 3 }}
          spacing="md"
          style={{ alignItems: "start" }}
        >
          {customCriteria.map((criterion) => {
            const custom = criterion.custom_def;
            return (
              <CriterionCard
                key={custom.key}
                criterion={criterion}
                entry={entryForCustomDef(custom)}
                issues={issuesByKey.get(custom.key)}
                dirty={dirtyByKey.get(custom.key) ?? false}
                onChange={setCriterion}
                onRemove={removeCriterion}
                onRevert={revertCriterion}
              />
            );
          })}
        </SimpleGrid>
        <Button
          variant="light"
          w="fit-content"
          leftSection={<IconPlus size={16} stroke={1.5} />}
          onClick={() => setCustomOpen(true)}
        >
          Add custom criterion
        </Button>
      </Stack>

      <CustomCriterionModal
        huntId={huntId}
        opened={customOpen}
        onClose={() => setCustomOpen(false)}
        onAdd={(criterion) =>
          setDraft((current) => [
            ...current,
            { ...criterion, position: current.length },
          ])
        }
      />

      <Modal opened={discardOpen} onClose={() => setDiscardOpen(false)} title="Discard changes?">
        <Stack>
          <Text size="sm">Your unsaved rubric edits will be lost.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDiscardOpen(false)}>
              Keep editing
            </Button>
            <Button
              color="red"
              onClick={() => {
                setDiscardOpen(false);
                onDone();
              }}
            >
              Discard
            </Button>
          </Group>
        </Stack>
      </Modal>

      <SettingsSaveBar
        dirtyLabels={dirtyLabels}
        saving={putRubric.isPending}
        onSave={attemptSave}
        onDiscard={cancel}
      />
    </Stack>
  );
}
