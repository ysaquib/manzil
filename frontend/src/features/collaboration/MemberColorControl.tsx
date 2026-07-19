import { ColorInput, Group, Select, Stack } from "@mantine/core";
import { useEffect, useState } from "react";

import { MEMBER_COLOR_TOKENS, memberColor } from "./memberColors";

const CUSTOM_SENTINEL = "__custom__";
const DEFAULT_CUSTOM = "#5C5CAA";
const HEX_RE = /^#[0-9A-Fa-f]{6}$/;

function isHexColor(value: string): boolean {
  return HEX_RE.test(value);
}

export function MemberColorControl({
  value,
  loading,
  onChange,
  label = "Palette color",
}: {
  value: string | null;
  loading: boolean;
  onChange: (color: string) => void;
  label?: string;
}) {
  const [customSelected, setCustomSelected] = useState(() =>
    Boolean(value && isHexColor(value)),
  );
  const [customColor, setCustomColor] = useState(() =>
    value && isHexColor(value) ? value : DEFAULT_CUSTOM,
  );

  useEffect(() => {
    if (value && isHexColor(value)) {
      setCustomSelected(true);
      setCustomColor(value);
    } else if (value && !value.startsWith("#")) {
      setCustomSelected(false);
    }
  }, [value]);

  const selectValue = customSelected || (value !== null && isHexColor(value)) ? CUSTOM_SENTINEL : value;

  return (
    <Stack gap="sm">
      <Select
        label={label}
        placeholder="Choose a color"
        data={[
          ...MEMBER_COLOR_TOKENS.map((token) => ({ value: token, label: token })),
          { value: CUSTOM_SENTINEL, label: "Custom color" },
        ]}
        value={selectValue}
        onChange={(next) => {
          if (!next) return;
          if (next === CUSTOM_SENTINEL) {
            setCustomSelected(true);
            return;
          }
          setCustomSelected(false);
          onChange(next);
        }}
        allowDeselect={false}
        renderOption={({ option }) => (
          <Group gap="xs">
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background:
                  option.value === CUSTOM_SENTINEL
                    ? customColor
                    : memberColor(option.value),
                display: "inline-block",
              }}
            />
            {option.label}
          </Group>
        )}
      />
      {customSelected && (
        <ColorInput
          label="Custom color"
          value={customColor}
          onChange={setCustomColor}
          onChangeEnd={(next) => {
            if (!HEX_RE.test(next)) return;
            const normalized = next.toUpperCase();
            setCustomColor(normalized);
            if (normalized.toUpperCase() === (value ?? "").toUpperCase()) return;
            onChange(normalized);
          }}
          format="hex"
          disabled={loading}
        />
      )}
    </Stack>
  );
}
