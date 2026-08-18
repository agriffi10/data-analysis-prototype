// Display formatters shared across features. Domain-specific ones (CSV name
// normalisation, Athena type names, and the file browser's own `formatSize`) stay with
// their feature — what lives here is what more than one feature renders the same way.

/**
 * Human-readable byte size (e.g. 1234567 → "1.2 MB"). `undefined` → em dash.
 *
 * Kept separate from {@link formatSize} for that `undefined` handling,
 * but sharing its TB ceiling, so one byte count never reads "3072.0 GB" on one screen
 * and "3.0 TB" on another. Lives here rather than in a feature because the query status
 * bar and the Data Explorer render the same scanned-bytes figure.
 */
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

/** Integer with locale thousands separators (e.g. 1384 → "1,384"). */
export function formatCount(n: number): string {
  return n.toLocaleString();
}

/** Human-readable duration from milliseconds (e.g. 800 → "800 ms", 1234 → "1.2s"). */
export function formatDurationMs(ms?: number): string {
  if (ms === undefined) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * A short absolute date, e.g. "Mar 3, 2026" — the one option set three call sites had
 * written out (two of them identical, differing only in key order).
 *
 * The locale is pinned to `en-US` because the app's copy is, and a month abbreviation
 * that switches language mid-sentence reads as a bug. Invalid input yields `''` rather
 * than "Invalid Date".
 *
 * @param value - An ISO-8601 string or a `Date`.
 */
export function formatAbsoluteDate(value: string | Date): string {
  const date = typeof value === 'string' ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-US', {year: 'numeric', month: 'short', day: 'numeric'});
}

/**
 * Coarse relative time from an ISO timestamp (e.g. "2 min ago", "Yesterday"), falling
 * back to `formatAbsoluteDate` beyond a week.
 *
 * @param iso - The ISO-8601 timestamp.
 * @param now - Reference time; pass to pin it (defaults to `Date.now()`).
 */
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
  return formatAbsoluteDate(iso);
}
