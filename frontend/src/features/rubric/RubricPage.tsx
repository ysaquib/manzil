// Rubric page (P1-12, §13.2): view mode default with single-page editor.
// Hunts with no enabled criteria open directly in edit mode.
import { Alert, Button, Center, Loader, Stack } from "@mantine/core";
import { IconPencil } from "@tabler/icons-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { useCatalog, useRubric } from "./api";
import { hasEnabledCriterion } from "./CreateRubricPrompt";
import { RubricEditor } from "./RubricEditor";
import { RubricView } from "./RubricView";
import { useHuntAccess } from "../hunts/access";

export function RubricPage() {
  const { huntId = "" } = useParams();
  const { data: catalog, isLoading: catalogLoading, error: catalogError } = useCatalog();
  const { data: saved, isLoading: rubricLoading, error: rubricError } = useRubric(huntId);
  const access = useHuntAccess(huntId);

  const isFirstRun = saved !== undefined && !hasEnabledCriterion(saved);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const effectiveMode = access.canMutate && isFirstRun ? "edit" : mode;

  if (catalogLoading || rubricLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (catalogError || rubricError) {
    return (
      <Alert color="red" title="Couldn't load the rubric">
        {(catalogError ?? rubricError)?.message}
      </Alert>
    );
  }

  if (!catalog || saved === undefined) return null;

  if (effectiveMode === "edit") {
    return (
      <RubricEditor
        huntId={huntId}
        catalog={catalog}
        saved={saved}
        onDone={() => setMode("view")}
      />
    );
  }

  return (
    <Stack gap="lg">
      <PageHeader
        title="Rubric"
        description="How listings are scored in this hunt"
        rightSlot={access.canMutate ? (
          <Button
            leftSection={<IconPencil size={16} stroke={1.5} />}
            onClick={() => setMode("edit")}
          >
            Edit
          </Button>
        ) : undefined}
      />
      <RubricView saved={saved} catalog={catalog} />
    </Stack>
  );
}
