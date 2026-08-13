import {formatAbsoluteDate} from '../../lib/format';

/**
 * Human-readable size, e.g. 1234 → "1.2 KB".
 *
 * SPEC-155 FR-007 decided the unit ceiling: TB, matching `lib/format.ts`'s
 * `formatBytes` (which lived in `features/query/` until SPEC-176 FR-004 moved it). It used to stop at GB, so a 3 TB object read "3072.0 GB" in the file
 * browser and "3.0 TB" in the query status bar — the same number, two answers, and
 * S3 allows objects up to 5 TB. A VISIBLE CHANGE, and the point of making it.
 *
 * The two functions still differ where the difference is defensible: this one takes a
 * required `number` (a listed object always has a size) and holds one decimal at every
 * unit; `formatBytes` takes `number | undefined` for a stat that may not have arrived
 * and drops the decimal above 10. Those are not the ceiling and were not merged.
 */
export function formatSize(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes < 1_099_511_627_776) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  return `${(bytes / 1_099_511_627_776).toFixed(1)} TB`;
}

/** Short last-modified date, e.g. "Mar 3, 2026". */
export function formatDate(date: Date): string {
  return formatAbsoluteDate(date);
}
