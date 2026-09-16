import {isAtRoot} from '../file-browser/fileBrowser.paths';

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
 * case is the one that matters: `/files?prefix=` seeds the browser's current folder
 * only from a prefix ending in `/`, so a file key passed through would open the space
 * root instead of the folder that holds the file.
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

/**
 * Split a location into its truncatable parent and its identifying final segment.
 *
 * A trailing slash stays with the NAME so a folder still reads as a folder once the parent
 * has been truncated away — `…/sales/` says "folder" where `…/sales` does not.
 */
export function splitLocation(location: string): {parent: string; name: string} {
  const trimmed = location.replace(/\/+$/, '');
  const cut = trimmed.lastIndexOf('/');
  const suffix = location.endsWith('/') ? '/' : '';
  if (cut === -1) return {parent: '', name: trimmed + suffix};
  return {parent: trimmed.slice(0, cut + 1), name: trimmed.slice(cut + 1) + suffix};
}

/**
 * Why a check cannot be run on the space root, shown on the start picker's disabled confirm and
 * on a report's Re-run.
 *
 * **The space root is not a data folder.** A check builds an external table over the folder it
 * is given, and Athena reads a table's location recursively, so a check at the top of a space
 * counts the portal's own bookkeeping — the query-results folder, archive receipts, shared-table
 * copies — as the user's data. It succeeds and reports the wrong numbers, which is why the
 * server refuses it (`location_is_space_root`) rather than qualifying the report.
 *
 * The picker takes the sentence alone, because it already knows when the user is standing at the
 * root and compares for itself. A caller holding a checked location rather than a browse position
 * asks {@link rerunRefusal}. The server's refusal is the real gate; this sentence exists so a user
 * never reaches it.
 */
export const CHECK_AT_ROOT_REFUSAL =
  'A check reads every file in the folder you give it, so it can’t be run here — the top of a space also ' +
  'holds your query results, archived copies and shared tables, and they’d be counted as your data. Open the ' +
  'folder holding the files you want checked, or pick a single file.';

/**
 * Why a report's check cannot be run again, or null when it can.
 *
 * Mirrors the server's top-level check (`location_is_space_root`, in the data-quality plane's
 * validate-authorize): a location that IS the space root is refused, and a file sitting at the
 * root is not, since every query over one file carries a path predicate that keeps its numbers its
 * own. A report can only name the root if it was written before the server refused one, and
 * re-running it would only be refused again, by notification, after the click.
 *
 * A report's location is the server's normalised form, which may lack a folder's trailing slash,
 * so it gains one before the comparison. The comparison is `isAtRoot`, as `createTableRefusal`'s
 * is: the browser already owns what "at the root" means.
 *
 * @param location - The location the report checked.
 * @param rootPrefix - The space root, trailing slash.
 * @returns The explanation, or null when the check can be run again.
 *
 * @example
 * rerunRefusal('alice', 'alice/');         // CHECK_AT_ROOT_REFUSAL
 * rerunRefusal('alice/top.csv', 'alice/'); // null
 */
export function rerunRefusal(location: string, rootPrefix: string): string | null {
  return isAtRoot(location.replace(/\/*$/, '/'), rootPrefix) ? CHECK_AT_ROOT_REFUSAL : null;
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
