// Display formatters for the query workspace.

/** Human-readable byte size (e.g. 1234567 → "1.2 MB"). `undefined` → em dash. */
export function formatBytes(bytes?: number): string {
  if (bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

/**
 * Normalizes a Save-results file name — appends ".csv" unless the user already
 * typed it (case-insensitive), never doubling it.
 */
export function normalizeCsvName(name: string): string {
  const trimmed = name.trim();
  return /\.csv$/i.test(trimmed) ? trimmed : `${trimmed}.csv`;
}

const ATHENA_TO_GLUE_TYPE: Record<string, string> = {
  varchar: 'string',
  integer: 'int',
  real: 'float',
  varbinary: 'binary'
};

/**
 * Maps Athena's Presto/Trino engine type names (`varchar`, `integer`, …) back
 * to the Hive/Glue DDL names the schema rail shows (`string`, `int`), so a
 * column reads the same in the results header as in the catalog. Unrecognized
 * types (including parameterized/complex ones like `decimal(10,2)`) pass
 * through unchanged.
 */
export function normalizeColumnType(type: string): string {
  return ATHENA_TO_GLUE_TYPE[type.trim().toLowerCase()] ?? type;
}
