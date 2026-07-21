import type {DataQualityReport} from './dataQuality.types';

/**
 * Report fixtures whose shapes and WORDING come from
 * `lambdas/data-quality-common/dqcommon/report.py`.
 *
 * The strings are copied from that module's constants and f-strings rather than
 * invented, because several tests assert that an approximate figure never renders
 * without its qualifier — and a fixture with made-up qualifier text would assert only
 * that this file agrees with itself.
 */

/** `report.py::NOTE_RAGGED`, verbatim — it must state BOTH over-counting causes. */
export const NOTE_RAGGED =
  'Approximate — over-counts rows with commas inside quotes, and rows with newlines inside quoted fields.';

/** `report.py::SKIP_TYPE_PARQUET`, verbatim. */
export const SKIP_TYPE_PARQUET = 'Parquet enforces types in the file format, so this check cannot find anything.';

/** `dq_byte_scan.py::SKIP_BINARY`, verbatim. */
export const SKIP_BINARY = 'binary format — encoding is defined by the file format';

/** `dq_byte_scan.py::SKIP_COMPRESSED`, verbatim. */
export const SKIP_COMPRESSED = 'compressed source — raw bytes are DEFLATE output';

/** `report.py::SKIP_RAGGED_NOT_LINE_DELIMITED`, verbatim. */
export const SKIP_RAGGED_NOT_LINE_DELIMITED = 'not a line-delimited text format.';

/** `report.py::NOT_COMPUTED_DUPLICATES`, verbatim. */
export const NOT_COMPUTED_DUPLICATES =
  'finding duplicates means comparing every column across the whole dataset, and that was too large to complete here.';

/** A CSV report with real findings — the common case the page is designed around. */
export function csvReport(over: Partial<DataQualityReport> = {}): DataQualityReport {
  return {
    requestId: 'req-1',
    location: 'alice/sales/',
    format: 'csv',
    fileCount: 3,
    verdict: 'issues_found',
    hasApproximateFigures: true,
    hasIncompleteFigures: false,
    completedAt: '2026-07-20T09:30:00Z',
    exact: {
      rowCount: 1_240_000,
      rowCountsByFile: [
        {key: 'alice/sales/jan.csv', rows: 500_000},
        {key: 'alice/sales/feb.csv', rows: 480_000},
        {key: 'alice/sales/mar.csv', rows: 260_000}
      ],
      duplicateRows: 12,
      columns: [
        {name: 'order_id', nullBlankRatio: 0, dominantType: 'BIGINT', nonParsingValues: 0, sampleOffending: []},
        {
          name: 'amount',
          nullBlankRatio: 0.0432,
          dominantType: 'DOUBLE',
          nonParsingValues: 412,
          sampleOffending: ['N/A', '-', '1,024']
        },
        {name: 'notes', nullBlankRatio: 0.61, dominantType: 'text', nonParsingValues: 0, sampleOffending: []}
      ],
      crossFile: {columnsAgree: true, disagreements: []}
    },
    approximate: {
      raggedRows: {count: 37, note: NOTE_RAGGED},
      encoding: {
        invalidUtf8Sequences: 4,
        sampleOffsets: [1024, 88123],
        coverage: 'sampled',
        coveragePercent: 12.5,
        note: 'Sampled — 12.5% of bytes examined.'
      }
    },
    topIssues: [
      '`amount` has 412 values that aren’t numbers in an otherwise numeric column',
      '37 rows have the wrong number of fields (approximate)',
      '4 invalid text encodings found, in the part examined — this data may have been exported in the wrong character set',
      '12 duplicate rows'
    ],
    ...over
  };
}

/**
 * A Parquet report: type consistency and encoding are both SKIPPED, and the verdict is
 * clean. This is the report that must never show a green result it did not earn.
 */
export function parquetReport(over: Partial<DataQualityReport> = {}): DataQualityReport {
  return {
    requestId: 'req-parquet',
    location: 'alice/warehouse/',
    format: 'parquet',
    fileCount: 2,
    verdict: 'clean',
    hasApproximateFigures: true,
    hasIncompleteFigures: true,
    completedAt: '2026-07-20T10:00:00Z',
    exact: {
      rowCount: 900,
      rowCountsByFile: [
        {key: 'alice/warehouse/a.parquet', rows: 500},
        {key: 'alice/warehouse/b.parquet', rows: 400}
      ],
      duplicateRows: 0,
      columns: [
        {name: 'id', nullBlankRatio: 0, typeConsistency: 'skipped', reason: SKIP_TYPE_PARQUET},
        {name: 'total', nullBlankRatio: 0.02, typeConsistency: 'skipped', reason: SKIP_TYPE_PARQUET}
      ],
      crossFile: {columnsAgree: true, disagreements: []}
    },
    approximate: {
      raggedRows: {status: 'skipped', reason: SKIP_RAGGED_NOT_LINE_DELIMITED},
      encoding: {status: 'skipped', reason: SKIP_BINARY}
    },
    topIssues: [],
    ...over
  };
}
