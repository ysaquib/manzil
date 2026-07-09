// Rubric builder (P1-12, §9.2/§13.2): Stepper wizard — choose criteria, set
// points/gates, review & save. Wizard output passes the same value_schema
// validation the API applies on PUT (done-when). Read-only rendering for
// non-Owners is Phase 2; Phase 1 is single-user.
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Stepper,
  Table,
  Text,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { ApiError } from "../../lib/apiClient";
import { semantic } from "../../theme";
import { CriterionCard } from "./CriterionCard";
import { useCatalog, usePutRubric, useRubric, type CatalogEntry, type RubricCriterion } from "./api";
import { deriveIsBonus, draftToPayload, initDraft, validateDraft } from "./rubricDraft";

const STEP_DESCRIPTIONS = [
  "Step 1 of 3 — Choose which criteria to score",
  "Step 2 of 3 — Set points and gates",
  "Step 3 of 3 — Review and save",
];

function ReviewTable({ draft, catalog }: { draft: RubricCriterion[]; catalog: CatalogEntry[] }) {
  const labelByKey = new Map(catalog.map((e) => [e.key, e.label]));
  const enabled = draft.filter((c) => c.enabled);
  if (enabled.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        Nothing enabled yet — listings can't be scored until the rubric has at least one criterion.
      </Text>
    );
  }
  return (
    <Table verticalSpacing="xs" withRowBorders={false}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            <Text size="xs" c="dimmed" fw={500}>
              Criterion
            </Text>
          </Table.Th>
          <Table.Th>
            <Text size="xs" c="dimmed" fw={500}>
              Configuration
            </Text>
          </Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {enabled.map((criterion) => (
          <Table.Tr key={criterion.catalog_key}>
            <Table.Td>
              <Text size="sm">
                {labelByKey.get(criterion.catalog_key ?? "") ?? criterion.catalog_key}
              </Text>
            </Table.Td>
            <Table.Td>
              <Group gap="xs">
                <Text size="xs" c="dimmed">
                  {criterion.options.length} option{criterion.options.length === 1 ? "" : "s"} ·
                  unknown {criterion.unknown_delta >= 0 ? "+" : ""}
                  {criterion.unknown_delta}
                </Text>
                {deriveIsBonus(criterion.options, criterion.unknown_delta) && (
                  <Badge size="xs" variant="light" color="green">
                    bonus
                  </Badge>
                )}
                {criterion.non_negotiable !== null && (
                  <Badge size="xs" variant="light" color={semantic.danger}>
                    non-negotiable
                  </Badge>
                )}
                {criterion.options.some((o) => o.dealbreaker_set_score !== null) && (
                  <Badge size="xs" variant="light" color={semantic.danger}>
                    dealbreaker
                  </Badge>
                )}
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function RubricWizard({
  huntId,
  catalog,
  saved,
}: {
  huntId: string;
  catalog: CatalogEntry[];
  saved: RubricCriterion[];
}) {
  const putRubric = usePutRubric(huntId);
  const isMobile = useMediaQuery("(max-width: 48em)");
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<RubricCriterion[]>(() => initDraft(catalog, saved));

  const entryByKey = new Map(catalog.map((e) => [e.key, e]));
  const issues = validateDraft(draft, catalog);
  const enabledCount = draft.filter((c) => c.enabled).length;

  const setCriterion = (next: RubricCriterion) =>
    setDraft((prev) => prev.map((c) => (c.catalog_key === next.catalog_key ? next : c)));

  const save = () =>
    putRubric.mutate(draftToPayload(draft), {
      onSuccess: () =>
        notifications.show({
          title: "Rubric saved",
          message: "Every listing re-scores in the background.",
          color: "green",
        }),
      onError: (error) =>
        notifications.show({
          title: "Couldn't save rubric",
          message: error instanceof ApiError ? error.message : "Unexpected error",
          color: "red",
        }),
    });

  return (
    <Stack gap="lg">
      <Text size="sm" c="dimmed">
        {STEP_DESCRIPTIONS[step]}
      </Text>
      <Stepper
        active={step}
        onStepClick={setStep}
        size="sm"
        orientation={isMobile ? "vertical" : "horizontal"}
      >
        <Stepper.Step label="Choose criteria" description={`${enabledCount} enabled`}>
          <Stack gap="sm" mt="md">
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
          </Stack>
        </Stepper.Step>
        <Stepper.Step label="Set points" description="deltas and gates">
          <Stack gap="sm" mt="md">
            {enabledCount === 0 && (
              <Text size="sm" c="dimmed">
                Enable criteria in the first step to set their points.
              </Text>
            )}
            {draft
              .filter((c) => c.enabled)
              .map((criterion) => {
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
          </Stack>
        </Stepper.Step>
        <Stepper.Step label="Review" description="check and save">
          <Stack gap="md" mt="md">
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
            <ReviewTable draft={draft} catalog={catalog} />
            <Group>
              <Button
                onClick={save}
                disabled={issues.length > 0 || enabledCount === 0}
                loading={putRubric.isPending}
              >
                Save rubric
              </Button>
              <Text size="xs" c="dimmed">
                Saving bumps the rubric version and re-scores every listing.
              </Text>
            </Group>
          </Stack>
        </Stepper.Step>
      </Stepper>
      <Group justify="space-between">
        <Button
          variant="default"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
        >
          Back
        </Button>
        {step < 2 && <Button onClick={() => setStep((s) => Math.min(2, s + 1))}>Next</Button>}
      </Group>
    </Stack>
  );
}

export function RubricWizardPage() {
  const { huntId = "" } = useParams();
  const { data: catalog, isLoading: catalogLoading, error: catalogError } = useCatalog();
  const { data: saved, isLoading: rubricLoading, error: rubricError } = useRubric(huntId);

  return (
    <Stack gap="lg">
      <PageHeader title="Rubric" description="Define how listings are scored in this hunt" />
      {(catalogLoading || rubricLoading) && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {(catalogError || rubricError) && (
        <Alert color="red" title="Couldn't load the rubric">
          {(catalogError ?? rubricError)?.message}
        </Alert>
      )}
      {catalog && saved && <RubricWizard huntId={huntId} catalog={catalog} saved={saved} />}
    </Stack>
  );
}
