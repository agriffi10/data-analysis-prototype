// SPEC-035 display formatters for query execution stats.

// Human-readable byte size (e.g. 1234567 → "1.2 MB"). `undefined` → em dash.
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

// Human-readable duration from milliseconds (e.g. 800 → "800 ms", 1234 → "1.2s").
export function formatDurationMs(ms?: number): string {
  if (ms === undefined) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// Coarse relative time from an ISO timestamp (e.g. "2 min ago", "Yesterday").
// Pass `now` (defaults to Date.now()) so callers/tests can pin the reference.
export function formatRelativeTime(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const seconds = Math.round((now - then) / 1000);
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds} sec ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return new Date(iso).toLocaleDateString();
}

// SPEC-049: normalize a Save-results file name — append ".csv" unless the user
// already typed it (case-insensitive), never doubling it.
export function normalizeCsvName(name: string): string {
  const trimmed = name.trim();
  return /\.csv$/i.test(trimmed) ? trimmed : `${trimmed}.csv`;
}

// Athena's result metadata reports the Presto/Trino engine type names (`varchar`,
// `integer`, …), which differ from the Hive/Glue DDL names the schema rail shows
// for the same column (`string`, `int`). Map the scalar engine names back to their
// Glue equivalents so a column defined as `string` in the catalog also reads
// `string` in the results header — not `varchar`. Unrecognized types (including
// parameterized/complex ones like `decimal(10,2)` or `array(...)`) pass through
// unchanged.
const ATHENA_TO_GLUE_TYPE: Record<string, string> = {
  varchar: 'string',
  integer: 'int',
  real: 'float',
  varbinary: 'binary'
};

export function normalizeColumnType(type: string): string {
  return ATHENA_TO_GLUE_TYPE[type.trim().toLowerCase()] ?? type;
}
