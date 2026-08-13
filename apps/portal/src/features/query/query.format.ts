// Display formatters for the query workspace. `formatBytes` is in `lib/format.ts`
// (SPEC-176 FR-004) and `normalizeColumnType` in `features/catalog/`.

/**
 * Normalizes a Save-results file name — appends ".csv" unless the user already
 * typed it (case-insensitive), never doubling it.
 */
export function normalizeCsvName(name: string): string {
  const trimmed = name.trim();
  return /\.csv$/i.test(trimmed) ? trimmed : `${trimmed}.csv`;
}
