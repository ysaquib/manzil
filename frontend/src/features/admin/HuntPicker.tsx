// Hunt typeahead for the admin panel (AD-3).
//
// The rule it exists to enforce: a picker never enumerates the table behind it.
// An installation with a hundred thousand Hunts would otherwise ship all of
// them to the browser the moment an admin clicked "Add to a Hunt", to render a
// list nobody can scroll anyway. So suggestions start at three characters and
// the server answers with at most twenty.
//
// Use this anywhere a Hunt is picked out of the whole installation. Pickers
// scoped to one Hunt's contents (a Property, a Floor Plan) are bounded by the
// Hunt and can go on rendering their full list.
import { Loader, Select } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useState, type CSSProperties } from "react";

import { HUNT_SEARCH_MIN_CHARS, useHuntOptions } from "./api";

export function HuntPicker({
  value,
  onChange,
  label,
  placeholder = "Search Hunts…",
  clearable = false,
  size = "xs",
  style,
}: {
  value: string | null;
  /** `label` is passed back so the caller can show the choice after picking. */
  onChange: (huntId: string | null, label: string | null) => void;
  label?: string;
  placeholder?: string;
  clearable?: boolean;
  size?: string;
  style?: CSSProperties;
}) {
  const [search, setSearch] = useState("");
  // Every keystroke is a request otherwise; 250ms is below the threshold where
  // the list feels like it is lagging the typing.
  const [debounced] = useDebouncedValue(search.trim(), 250);
  const options = useHuntOptions(debounced);
  const short = debounced.length < HUNT_SEARCH_MIN_CHARS;

  // The picked Hunt is kept in the option list by hand: the server's answer is
  // whatever matches the *current* search, and once the input is cleared the
  // chosen row would otherwise vanish from `data` and take its label with it.
  const [picked, setPicked] = useState<{ value: string; label: string } | null>(null);

  const data = [
    ...(picked && !options.data?.some((hunt) => hunt.hunt_id === picked.value)
      ? [picked]
      : []),
    ...(options.data ?? []).map((hunt) => ({
      value: hunt.hunt_id,
      label: hunt.owner_name ? `${hunt.name} — ${hunt.owner_name}` : hunt.name,
    })),
  ];

  return (
    <Select
      size={size}
      label={label}
      placeholder={placeholder}
      style={style}
      searchable
      clearable={clearable}
      data={data}
      value={value}
      searchValue={search}
      onSearchChange={setSearch}
      // The server already decided what matches — it searched owner names too,
      // which the label may not contain. Filtering again client-side would drop
      // exactly those rows.
      filter={({ options: opts }) => opts}
      rightSection={options.isFetching ? <Loader size={12} /> : undefined}
      nothingFoundMessage={
        short
          ? `Type ${HUNT_SEARCH_MIN_CHARS} characters to search`
          : options.isFetching
            ? "Searching…"
            : "No Hunt matches"
      }
      onChange={(next, option) => {
        setPicked(next && option ? { value: next, label: option.label } : null);
        onChange(next, option?.label ?? null);
      }}
    />
  );
}
