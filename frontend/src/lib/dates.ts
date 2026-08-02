/** Local calendar date as YYYY-MM-DD (no UTC shift). */
export function dateInputValue(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** Parse an ISO date string (YYYY-MM-DD) as local midnight. */
export function parseLocalDate(iso: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return new Date(year, month - 1, day);
}

/** Read a Mantine DatePicker value as a local ISO date string. */
export function datePickerToIso(value: Date | string | null): string | null {
  if (value === null) return null;
  if (value instanceof Date) return dateInputValue(value);
  const parsed = parseLocalDate(String(value));
  return parsed ? dateInputValue(parsed) : null;
}
