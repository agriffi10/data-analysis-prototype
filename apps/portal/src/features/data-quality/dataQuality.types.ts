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
 * The wire envelope. `idToken` is attached at send time and never stored.
 *
 * There is deliberately NO actor/username field: the actor is derived server-side from
 * the verified token claim, so a body cannot assert an identity.
 */
export type DataQualityMessage = DataQualityRequest & {idToken: string};

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
  hasApproximateFigures: boolean;
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
 * One column's exact findings.
 *
 * `nullBlankRatio` sits on BOTH branches because `report.py::_column` writes it before
 * it branches: a column whose type check was skipped still has a real, exact null/blank
 * ratio, and suppressing it would hide a genuine figure behind an unrelated skip.
 */
export type ColumnFinding = {name: string; nullBlankRatio: number} & (
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

export type EncodingFigure =
  | {
      invalidUtf8Sequences: number;
      sampleOffsets: number[];
      /** Absent on a malformed byte-scan block; treat an absent value as sampled. */
      coverage?: 'complete' | 'sampled';
      coveragePercent: number;
      note: string;
    }
  | SkippedFigure // Parquet (binary format) or .gz (DEFLATE output)
  | NotComputedFigure; // an absent byte-scan block — "an absent figure is not a clean one"

export type CrossFileDisagreement = {file: string; missing: string[]; extra: string[]};

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
  exact: {
    rowCount: number;
    /** Sorted by key and reconciled against the manifest, so its length === fileCount. */
    rowCountsByFile: {key: string; rows: number}[];
    duplicateRows: number | NotComputedFigure;
    columns: ColumnFinding[];
    crossFile: {columnsAgree: boolean; disagreements: CrossFileDisagreement[]};
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

export function isSkipped(figure: unknown): figure is SkippedFigure {
  return !!figure && (figure as SkippedFigure).status === 'skipped';
}

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
