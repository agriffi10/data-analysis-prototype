/**
 * The last meaningful segment of an S3 key or folder prefix, for use as a short label.
 *
 * Trailing slashes are stripped first, so a folder prefix yields the folder's own name
 * rather than an empty string. A location that is nothing but slashes, or empty, falls
 * back to the original input so a label is never blank.
 *
 * @example
 * locationLabel('alice/data/sales/')    // 'sales'
 * locationLabel('alice/data/sales.csv') // 'sales.csv'
 */
export function locationLabel(location: string): string {
  const trimmed = location.replace(/\/+$/, '');
  return trimmed.slice(trimmed.lastIndexOf('/') + 1) || location;
}

/**
 * The FOLDER that holds a checked location, as a prefix ending in `/`.
 *
 * A folder location is returned as-is; a file key is reduced to its parent. The file
 * case is the one that matters: `/files?prefix=` seeds the browser's current folder,
 * so passing a file key through would ask it to open a folder that does not exist.
 *
 * @example
 * sourceFolderPrefix('alice/data/sales/')    // 'alice/data/sales/'
 * sourceFolderPrefix('alice/data/sales.csv') // 'alice/data/'
 */
export function sourceFolderPrefix(location: string): string {
  if (location.endsWith('/')) return location;
  const cut = location.lastIndexOf('/');
  return cut === -1 ? '' : location.slice(0, cut + 1);
}

/** A dominant type for display. The Lambda upper-cases matched casts but not `text`. */
export function dominantTypeLabel(type: string): string {
  return type.toUpperCase();
}

/** A null/blank ratio (0–1) as a percentage string, e.g. 0.0432 → "4.3%". */
export function formatRatio(ratio: number): string {
  if (!Number.isFinite(ratio)) return '—';
  const percent = ratio * 100;
  // Distinguish "none" from "rounds to none": a column with a handful of blanks in a
  // million rows is not the same as one with no blanks, and 0.0% would claim it is.
  if (percent === 0) return '0%';
  if (percent < 0.1) return '<0.1%';
  return `${percent.toFixed(1)}%`;
}

/**
 * Present a Lambda-authored `reason` as a standalone sentence.
 *
 * Every reason in `dqcommon` is written as a lower-case FRAGMENT, because on its own
 * surface it completes a clause: `Couldn't check data quality: {reason}`. This view
 * shows reasons on their own, after a bold lead, where the fragment reads as a
 * mistake — "Not applicable. not a line-delimited text format." So the first letter is
 * capitalized and a full stop added when missing.
 *
 * Presentation only: no word is changed, and a reason already starting with a proper
 * noun ("Parquet enforces types…") is untouched.
 */
export function asSentence(reason: string): string {
  const trimmed = reason.trim();
  if (!trimmed) return '';
  const capitalized = trimmed[0].toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalized) ? capitalized : `${capitalized}.`;
}

/** An ISO-8601 timestamp as a readable absolute date-time; invalid input yields ''. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

/**
 * Substrings that mark a top-issue line as resting on an APPROXIMATE figure.
 *
 * These mirror `dqcommon/report.py::top_issues`, which authors every one of these
 * strings. It has exactly four generators: cross-file disagreements, ragged rows,
 * encoding, and per-column type failures — and only the middle two are approximate.
 * Ragged lines end in `(approximate)`; encoding lines always contain the phrase below,
 * and are approximate whether or not the scan was additionally sampled (the whole
 * check lives in the report's `approximate` block).
 *
 * The wordings are pinned by test. If report.py's wording ever drifts, an issue would
 * be labelled `Exact` when it is not — so the test exists to make that drift loud
 * rather than to decorate the classifier.
 */
export const APPROXIMATE_ISSUE_MARKERS = ['(approximate)', 'invalid text encoding'] as const;

/** Whether a top-issue line rests on an approximate figure (see the markers above). */
export function isApproximateIssue(issue: string): boolean {
  const lowered = issue.toLowerCase();
  return APPROXIMATE_ISSUE_MARKERS.some((marker) => lowered.includes(marker));
}
