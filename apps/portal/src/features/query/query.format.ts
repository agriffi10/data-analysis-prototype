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
