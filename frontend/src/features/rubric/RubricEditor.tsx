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
import { IconDeviceFloppy } from "@tabler/icons-react";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { PageHeader } from "../../components/PageHeader";
import { ApiError } from "../../lib/apiClient";
import { semantic } from "../../theme";
import type { CatalogEntry, RubricCriterion } from "./api";
import { usePutRubric } from "./api";
import { CriterionCard } from "./CriterionCard";
import { draftToPayload, initDraft, validateDraft } from "./rubricDraft";

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

  const entryByKey = new Map(catalog.map((e) => [e.key, e]));
  const issues = validateDraft(draft, catalog);
  const enabledCount = draft.filter((c) => c.enabled).length;

  const setCriterion = (next: RubricCriterion) =>
    setDraft((prev) => prev.map((c) => (c.catalog_key === next.catalog_key ? next : c)));

  const save = () =>
    putRubric.mutate(draftToPayload(draft), {
      onSuccess: () => {
        notifications.show({
          title: "Rubric saved",
          message: "Every listing re-scores in the background.",
          color: "green",
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
        <Alert color={semantic.danger} title="Fix before saving">
          <Stack gap={4}>
            {issues.map((issue, i) => (
              <Text size="sm" key={i}>
                {entryByKey.get(issue.catalogKey)?.label ?? issue.catalogKey}: {issue.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
        {draft.map((criterion) => {
          const entry = entryByKey.get(criterion.catalog_key ?? "");
          return entry ? (
            <CriterionCard
              key={entry.key}
              criterion={criterion}
              entry={entry}
              onChange={setCriterion}
            />
          ) : null;
        })}
      </SimpleGrid>

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
