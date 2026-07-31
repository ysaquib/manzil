import {
  Alert,
  Button,
  Group,
  Modal,
  Radio,
  SegmentedControl,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useState } from "react";

import type { RubricOption } from "../../lib/contracts";
import type {
  CustomRoute,
  RubricCriterion,
} from "./api";
import { useClassifyCustomRouting } from "./api";
import type { ValueSchema } from "./widgets/types";

function optionsFor(schema: ValueSchema): RubricOption[] {
  if (schema.type === "boolean") {
    return [true, false].map((value) => ({
      match: { op: "bool", value },
      delta: 0,
      dealbreaker_set_score: null,
    }));
  }
  const value = schema.type === "string" ? schema.enum?.[0] ?? "" : 0;
  return [{ match: { op: "eq", value }, delta: 0, dealbreaker_set_score: null }];
}

export function CustomCriterionModal({
  huntId,
  opened,
  onClose,
  onAdd,
}: {
  huntId: string;
  opened: boolean;
  onClose: () => void;
  onAdd: (criterion: RubricCriterion) => void;
}) {
  const classify = useClassifyCustomRouting(huntId);
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [key, setKey] = useState<string | null>(null);
  const [route, setRoute] = useState<CustomRoute>(null);
  const [reason, setReason] = useState("");
  const [unsupported, setUnsupported] = useState(false);
  const [scope, setScope] = useState<"property" | "floor_plan">("property");
  const [valueType, setValueType] = useState<"boolean" | "number" | "enum">("boolean");
  const [enumValues, setEnumValues] = useState<string[]>([]);

  const reset = () => {
    setLabel("");
    setDescription("");
    setKey(null);
    setRoute(null);
    setReason("");
    setUnsupported(false);
    setScope("property");
    setValueType("boolean");
    setEnumValues([]);
  };
  const close = () => {
    reset();
    onClose();
  };
  const classifyRoute = () =>
    classify.mutate(
      { label, description },
      {
        onSuccess: (result) => {
          setKey(result.key);
          setRoute(result.suggested_requires_tool);
          setReason(result.reason);
          setUnsupported(!result.supported);
          if (result.suggested_requires_tool === "maps") setScope("property");
        },
      },
    );

  const canClassify = label.trim().length > 0 && description.trim().length > 0;
  const normalizedEnum = enumValues.map((value) => value.trim()).filter(Boolean);
  const canAdd =
    key !== null &&
    (route === null || route === "maps") &&
    !(route === "maps" && scope === "floor_plan") &&
    (valueType !== "enum" ||
      (normalizedEnum.length >= 2 &&
        new Set(normalizedEnum).size === normalizedEnum.length));

  const add = () => {
    if (!key || !canAdd) return;
    const valueSchema: ValueSchema =
      valueType === "boolean"
        ? { type: "boolean" }
        : valueType === "number"
          ? { type: "number" }
          : { type: "string", enum: normalizedEnum };
    onAdd({
      catalog_key: null,
      custom_def: {
        schema_version: 1,
        key,
        label: label.trim(),
        description: description.trim(),
        fact_scope: scope,
        value_schema: valueSchema,
        requires_tool: route,
        refresh_class: route === "maps" ? "location" : "listing_details",
        routing_confirmed: true,
      },
      enabled: true,
      options: optionsFor(valueSchema),
      unknown_delta: 0,
      non_negotiable: null,
      is_bonus: true,
      position: 0,
    });
    close();
  };

  return (
    <Modal opened={opened} onClose={close} title="Add custom criterion" centered>
      <Stack>
        <TextInput label="Name" value={label} onChange={(event) => setLabel(event.currentTarget.value)} />
        <Textarea
          label="What should Manzil determine?"
          description="State the evidence or calculation plainly."
          value={description}
          minRows={3}
          onChange={(event) => setDescription(event.currentTarget.value)}
        />
        {key === null ? (
          <>
            {classify.isError && (
              <Alert color="red" title="Couldn't suggest routing">
                Try again. Nothing has been added to the Rubric.
              </Alert>
            )}
            <Button onClick={classifyRoute} disabled={!canClassify} loading={classify.isPending}>
              Suggest routing
            </Button>
          </>
        ) : (
          <>
            <Stack gap="xs">
              <Text size="sm" fw={600}>Confirm routing</Text>
              {reason && <Text size="sm" c="dimmed">{reason}</Text>}
              {unsupported && (
                <Alert color="yellow" title="That route is not available yet">
                  Vision and web-search custom Criteria need separate quality and security contracts.
                  Choose listing text or Maps to continue.
                </Alert>
              )}
              <Radio.Group
                value={route ?? "text"}
                onChange={(value) => {
                  const next = value === "text" ? null : (value as CustomRoute);
                  setRoute(next);
                  setUnsupported(false);
                  if (next === "maps") setScope("property");
                }}
              >
                <Group>
                  <Radio value="text" label="Listing text" />
                  <Radio value="maps" label="Google Maps" />
                </Group>
              </Radio.Group>
            </Stack>
            <SegmentedControl
              aria-label="Fact scope"
              value={scope}
              onChange={(value) => setScope(value as "property" | "floor_plan")}
              disabled={route === "maps"}
              data={[
                { value: "property", label: "Property" },
                { value: "floor_plan", label: "Floor Plan" },
              ]}
            />
            <SegmentedControl
              aria-label="Value type"
              value={valueType}
              onChange={(value) => setValueType(value as typeof valueType)}
              data={[
                { value: "boolean", label: "Yes / no" },
                { value: "number", label: "Number" },
                { value: "enum", label: "Choices" },
              ]}
            />
            {valueType === "enum" && (
              <TagsInput
                label="Allowed values"
                description="Add at least two distinct choices."
                value={enumValues}
                onChange={setEnumValues}
              />
            )}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>Cancel</Button>
              <Button onClick={add} disabled={!canAdd}>Confirm and add</Button>
            </Group>
          </>
        )}
      </Stack>
    </Modal>
  );
}
