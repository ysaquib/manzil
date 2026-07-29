// Member color picker (P3-16 reshape, DESIGN §20 v3.27): a row of swatches
// rather than a dropdown.
//
// A color is chosen by looking at it, so the six palette tokens are all visible
// at once — a Select hid every option behind a click and named them in words
// ("moss", "ochre") that only mean anything once you have already seen the
// color. The seventh swatch opens the custom picker and previews the custom
// color it would apply.
import { ColorInput, Group, Stack, Text, UnstyledButton } from "@mantine/core";
import { IconPencil } from "@tabler/icons-react";
import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { MEMBER_COLOR_TOKENS, memberColor } from "./memberColors";
import classes from "./MemberColorControl.module.css";

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

  // One source of truth for "the custom picker is in play". The effect above
  // keeps it in step with an incoming hex value, and the initial state derives
  // from it — so deriving a second answer from `value` here would only
  // disagree in the moment between clicking a token and the parent's re-render.
  const usingCustom = customSelected;

  return (
    <Stack gap="xs">
      {label && (
        <Text size="sm" fw={500}>
          {label}
        </Text>
      )}
      <Group gap="xs" role="radiogroup" aria-label={label || "Color"}>
        {MEMBER_COLOR_TOKENS.map((token) => {
          const selected = !usingCustom && value === token;
          return (
            <UnstyledButton
              key={token}
              role="radio"
              aria-label={token}
              aria-checked={selected}
              data-selected={selected || undefined}
              className={classes.swatch}
              style={{ "--swatch": memberColor(token) } as CSSProperties}
              disabled={loading}
              onClick={() => {
                setCustomSelected(false);
                onChange(token);
              }}
            />
          );
        })}
        <UnstyledButton
          role="radio"
          aria-label="Pick a custom color"
          aria-checked={usingCustom}
          data-selected={usingCustom || undefined}
          className={`${classes.swatch} ${classes.custom}`}
          style={{ "--swatch": customColor } as CSSProperties}
          disabled={loading}
          onClick={() => setCustomSelected(true)}
        >
          <IconPencil size={13} stroke={2} className={classes.customIcon} />
        </UnstyledButton>
      </Group>

      {usingCustom && (
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
