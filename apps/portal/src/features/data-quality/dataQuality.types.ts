/** Which space a quality check targets. */
export type DataQualitySpaceKind = 'personal' | 'shared';

export type DataQualitySpace = {
  kind: DataQualitySpaceKind;
  bucket: string;
  /** The space root prefix: `{username}/` or `{spaceName}/`. */
  prefix: string;
};

export type DataQualityRequest = {
  /** UUIDv4, browser-minted. Keys the manifest, the intermediate results, and the report. */
  requestId: string;
  space: DataQualitySpace;
  /** The file or folder key to check, relative to the bucket. */
  location: string;
};

/**
 * One row on the runs dashboard.
 *
 * Mirrors an entry in `{space}/_data-quality-reports/index.json`, written by
 * `dqcommon/index_store.py::entry_from`. Deliberately small: this file is fetched whole on
 * every dashboard load, so it carries what a ROW renders and nothing else — the findings
 * live in the per-run report, fetched only on drill-down.
 */
export type DataQualityRunSummary = {
  requestId: string;
  /**
   * CLIENT-DERIVED from whichever space's index this came out of — it is NOT stored in the
   * entry. Storing it would be a second copy of a fact the object's own key already states,
   * free to drift; deriving it makes the row's `/data-quality/{space}/{requestId}` link
   * correct by construction.
   */
  space: string;
  location: string;
  format: string;
  verdict: DataQualityVerdict;
  fileCount: number;
  /**
   * The report's `hasIncompleteFigures`: a check was skipped or failed, or the encoding scan
   * only sampled the bytes. It drives the row's Partly checked tag, which is the same flag
   * the report banner warns on. An entry written before the index carried it reads as
   * `true`, so an old run never shows as an unqualified Clean.
   */
  hasIncompleteFigures: boolean;
  /** The report's `completedAt`. */
  timestamp: string;
};

// ── The report ────────────────────────────────────────────
//
// Mirrors `lambdas/data-quality-common/dqcommon/report.py::build` BYTE-FOR-BYTE. The
// Lambda owns this shape; the SPA reflects it and never reinterprets it. When these
// types and that module disagree, that module is right — it is what actually writes
// the object.

export type DataQualityVerdict = 'clean' | 'issues_found';

/** A check that could never have applied here. NEVER render it as a clean pass. */
export type SkippedFigure = {status: 'skipped'; reason: string};

/** A check that was attempted and failed. Also never a clean pass. */
export type NotComputedFigure = {status: 'not_computed'; reason: string};

/**
 * How many entries of a list the report left out because it would have been too large to open.
 * Written beside the list it counts, named after it, and only when something was left out — the
 * list keeps its first entries, so absent reads as "every entry is listed".
 */
export type Unlisted = number;

/**
 * One column's exact findings.
 *
 * `nullBlankRatio` sits on BOTH branches because `report.py::_column` writes it before
 * it branches: a column whose type check was skipped still has a real, exact null/blank
 * ratio, and suppressing it would hide a genuine figure behind an unrelated skip.
 *
 * `otherSpellings` is present only on a column merged from headers that differ only by
 * case across files — Athena reads them as one column — and is absent on every report
 * written before that merge existed. `otherSpellingsUnlisted` counts the spellings left out of it.
 */
export type ColumnFinding = {
  name: string;
  nullBlankRatio: number;
  otherSpellings?: string[];
  otherSpellingsUnlisted?: Unlisted;
} & (
  | {typeConsistency: 'skipped'; reason: string}
  | {dominantType: DominantType; nonParsingValues: number; sampleOffending: string[]}
);

/**
 * A matched cast is upper-cased by the Lambda; the free-text fallback is the lower-case
 * literal `'text'`. That inconsistency is in the shipped report, so the view normalizes
 * for display rather than assuming either casing.
 */
export type DominantType = 'BIGINT' | 'DOUBLE' | 'TIMESTAMP' | 'DATE' | 'text';

export type RaggedRowsFigure =
  | {count: number; note: string}
  | NotComputedFigure // a degraded query, or a line over Athena's 200 MB limit
  | SkippedFigure; // non-CSV — not a line-delimited text format

/**
 * One example of invalid text encoding: which object it is in, and how far into that object.
 *
 * A bare offset is unreadable across a folder, so `dq_byte_scan.py::_scan_all` records the key
 * beside it and `report.py::_encoding` passes the entries through untouched. This file typed the
 * field `number[]` for as long as nothing rendered it, which cost nothing and was never true.
 */
export type EncodingExample = {key: string; offset: number};

/**
 * Up to `DQ_DUPLICATE_SAMPLE` of the most-repeated rows, or the sentence saying why there are
 * none to show.
 *
 * `columns` is the grouping's own column list — `sql.grouped_column_names`, the profiled columns
 * followed by the partition keys — and NOT the report's `exact.columns`, which is a different
 * list in a CSV whose header names a partition. Each row's `values` line up with it positionally.
 */
export type DuplicateSampleRow = {repeats: number; values: (string | null)[]};

export type DuplicateSamples = {columns: string[]; rows: DuplicateSampleRow[]} | {omitted: string};

export type EncodingFigure =
  | {
      invalidUtf8Sequences: number;
      sampleOffsets: EncodingExample[];
      /** Absent on a malformed byte-scan block; treat an absent value as sampled. */
      coverage?: 'complete' | 'sampled';
      coveragePercent: number;
      note: string;
    }
  | SkippedFigure // Parquet (binary format) or .gz (DEFLATE output)
  | NotComputedFigure; // an absent byte-scan block — "an absent figure is not a clean one"

export type CrossFileDisagreement = {
  file: string;
  missing: string[];
  extra: string[];
  /**
   * The file's fields do not line up with the report's columns, so its values are counted under
   * the wrong names. Only ever true for a CSV, which is read by position. Optional because a report
   * written before the field existed lacks it, and absent reads as false.
   */
  shifted?: boolean;
};

/**
 * A column named after one of the folder's partitions, and what the check did with it. Its own
 * name cannot be a column of a table that also has the partition, so a CSV, which is read by
 * position, keeps it under a new name (`as`), and JSON and Parquet, which are read by name, leave
 * it out of the column figures. `name` is spelled as the files spell it.
 */
export type PartitionNamedColumn = {name: string; outcome: 'renamed'; as: string} | {name: string; outcome: 'omitted'};

export type DataQualityReport = {
  requestId: string;
  location: string;
  format: string;
  fileCount: number;
  verdict: DataQualityVerdict;
  /**
   * True on EVERY report this arc produces (`report.py::_has_approximate`: ragged and
   * encoding are `approximate` when computed and `skipped` when not, so neither has an
   * exact branch). It can therefore only qualify SOFTLY — never warn, or the warning
   * would fire on a spotless CSV and be learned as noise.
   */
  hasApproximateFigures: boolean;
  /** The flag that actually varies: something was skipped or failed. This one warns. */
  hasIncompleteFigures: boolean;
  /** ISO-8601. The only field a replay changes — the key is a pure function of requestId. */
  completedAt: string;
  /** Optional because a report written before the field existed lacks it; absent reads as none. */
  partitionNamedColumns?: PartitionNamedColumn[];
  exact: {
    rowCount: number;
    /**
     * Sorted by key and reconciled against the manifest, so its length plus
     * `rowCountsByFileUnlisted` === fileCount.
     */
    rowCountsByFile: {key: string; rows: number}[];
    rowCountsByFileUnlisted?: Unlisted;
    duplicateRows: number | NotComputedFigure;
    /**
     * Absent on a report written before the samples existed, and on one whose duplicate count was
     * not computed. Absent reads as nothing to show, never as no duplicates.
     */
    duplicateSamples?: DuplicateSamples;
    columns: ColumnFinding[];
    crossFile: {columnsAgree: boolean; disagreements: CrossFileDisagreement[]; disagreementsUnlisted?: Unlisted};
  };
  approximate: {raggedRows: RaggedRowsFigure; encoding: EncodingFigure};
  /** At most 5, severity-ordered, structural findings first. */
  topIssues: string[];
};

// ── Narrowing helpers ───────────────────────────────────────────────────────
// The report's figures are discriminated by a `status` key that is PRESENT ONLY on the
// skipped/not_computed variants — there is no `status: 'ok'` arm. These exist so no
// render site has to re-derive that, and so `skipped` and `not_computed` can never be
// collapsed: "this could never apply" and "we tried and failed" are different things,
// and blurring them is precisely what would let a Parquet report show a green result it
// did not earn.

/** True when a figure was deliberately not attempted for this file's format. */
export function isSkipped(figure: unknown): figure is SkippedFigure {
  return !!figure && (figure as SkippedFigure).status === 'skipped';
}

/** True when a figure was attempted and could not be produced. */
export function isNotComputed(figure: unknown): figure is NotComputedFigure {
  return !!figure && (figure as NotComputedFigure).status === 'not_computed';
}

/** True when a figure carries no measurement at all — either skipped or not computed. */
export function isUnmeasured(figure: unknown): figure is SkippedFigure | NotComputedFigure {
  return isSkipped(figure) || isNotComputed(figure);
}

/** The column variant that has a real type-consistency measurement behind it. */
export function isTypedColumn(
  column: ColumnFinding
): column is ColumnFinding & {dominantType: DominantType; nonParsingValues: number; sampleOffending: string[]} {
  return !('typeConsistency' in column);
}
