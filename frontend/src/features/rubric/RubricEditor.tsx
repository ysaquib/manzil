// Single-page rubric editor (§13.2): all criteria on one scrollable page with
// inline validation. Replaces the former 3-step Stepper wizard.
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
import { useState } from "react";

import { PageHeader } from "../../components/PageHeader";
import { ApiError } from "../../lib/apiClient";
import type { CatalogEntry, CustomCriterionDef, RubricCriterion } from "./api";
import { usePutRubric } from "./api";
import { CustomCriterionModal } from "./CustomCriterionModal";
import { criterionKey, customCatalogEntry } from "./customCriterion";
import { CriterionCard } from "./CriterionCard";
import { CriterionGroupHeader } from "./CriterionGroupHeader";
import { CriterionPicker } from "./CriterionPicker";
import { groupCatalog } from "./catalogGroups";
import { draftToPayload, initDraft, overlapWarnings, validateDraft } from "./rubricDraft";

function isDirty(
  draft: RubricCriterion[],
  catalog: CatalogEntry[],
  saved: RubricCriterion[],
): boolean {
  const baseline = draftToPayload(initDraft(catalog, saved));
  return JSON.stringify(draftToPayload(draft)) !== JSON.stringify(baseline);
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

  const customCriteria = draft.filter(
    (criterion): criterion is RubricCriterion & { custom_def: CustomCriterionDef } =>
      criterion.custom_def !== null,
  );
  const customEntries = customCriteria.map((criterion) =>
    customCatalogEntry(criterion.custom_def),
  );
  const entryByKey = new Map([...catalog, ...customEntries].map((e) => [e.key, e]));
  const issues = validateDraft(draft, catalog);
  const warnings = overlapWarnings(draft, catalog);
  const infoWarnings = warnings.filter((warning) => warning.tone === "info");
  const reviewWarnings = warnings.filter((warning) => warning.tone !== "info");
  const enabledCount = draft.filter((c) => c.enabled).length;
  const criterionByKey = new Map(
    draft
      .map((criterion) => [criterionKey(criterion), criterion] as const)
      .filter((entry): entry is readonly [string, RubricCriterion] => entry[0] !== null),
  );

  const setCriterion = (next: RubricCriterion) =>
    setDraft((prev) =>
      prev.map((criterion) =>
        criterionKey(criterion) === criterionKey(next) ? next : criterion,
      ),
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
              onClick={save}
              disabled={issues.length > 0 || enabledCount === 0}
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

      {issues.length > 0 && (
        <Alert color={"red"} title="Fix before saving">
          <Stack gap={4}>
            {issues.map((issue, i) => (
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

      {groupCatalog(catalog).map((group) => {
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
                    onChange={setCriterion}
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
                entry={customCatalogEntry(custom)}
                onChange={setCriterion}
                onRemove={() =>
                  setDraft((current) =>
                    current.filter((item) => criterionKey(item) !== custom.key),
                  )
                }
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
    </Stack>
  );
}
