/** Human-friendly rendering of an unknown slot value. Returns null for "empty". */
export function formatValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() === "" ? null : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    if (value.every((v) => typeof v === "string" || typeof v === "number")) return value.join(", ");
    return JSON.stringify(value);
  }
  return JSON.stringify(value);
}

/** String used to pre-fill an edit input for a slot value. */
export function editableString(value: unknown): string {
  const s = formatValue(value);
  return s ?? "";
}

export function percent(n: number): string {
  return `${Math.round(n * 100)}%`;
}
