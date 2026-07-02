/**
 * Human-readable size, e.g. 1234 → "1.2 KB". Caps at GB. (The query feature has
 * a separate `formatBytes` with different rules — undefined handling, TB,
 * variable precision — deliberately not merged.)
 */
export function formatSize(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
}
