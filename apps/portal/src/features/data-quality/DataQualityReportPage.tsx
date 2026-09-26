import {useId} from 'react';
import {useParams, useNavigate} from 'react-router';
import {PageLayout} from '../../components/PageLayout';
import {Banner} from '../../components/Banner';
import {Button} from '../../components/Button';
import {StatusPill} from '../../components/StatusPill';
import {WarningIcon, InfoIcon} from '../../components/icons';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useIsMobile} from '../../lib/useBreakpoint';
import {cx} from '../../lib/cx';
import {formatCount} from '../../lib/format';
import {useDataQualityReport} from './useDataQualityReport';
import {useDataQualityCheck} from './useDataQualityCheck';
import {useCanFollowLink} from '../feature-flags';
import {
  asSentence,
  dominantTypeLabel,
  formatRatio,
  formatTimestamp,
  isApproximateIssue,
  rerunRefusal,
  sourceFolderPrefix
} from './dataQuality.format';
import {isTypedColumn, isUnmeasured, isSkipped} from './dataQuality.types';
import {relativePath} from '../file-browser/fileBrowser.paths';
import {EMPTY_DISPLAY, NULL_DISPLAY} from '../data-explorer/cellText';
import type {
  ColumnFinding,
  CrossFileDisagreement,
  DataQualityReport,
  DuplicateSampleRow,
  DuplicateSamples,
  EncodingFigure,
  PartitionNamedColumn,
  RaggedRowsFigure
} from './dataQuality.types';

// ── Chips ───────────────────────────────────────────────────────────────────

type ChipTone = 'danger' | 'warning' | 'success';
type ChipLabel = 'Exact' | 'Approximate' | 'Sampled' | 'Skipped' | 'Not computed';

/**
 * The shared `StatusPill`, which now owns the shape this file used to
 * reproduce: a dot PLUS a text label, never colour alone. The label is what carries the
 * meaning — the tone is decoration, and a user who cannot distinguish the tones loses nothing.
 */
function StatusChip({label, tone}: {label: ChipLabel; tone: ChipTone}) {
  return <StatusPill tone={tone}>{label}</StatusPill>;
}

// ── Callout (the HelpGuideCard shape) ───────────────────────────────────────

/**
 * The `HelpGuideCard` callout shape: a bordered, tinted box with an icon and a leading
 * bold clause. Used for every qualifier, because a qualifier that reads as body text is
 * one a user skims past — and an unqualified approximate figure is the single most
 * misleading thing this page could show.
 */
function Callout({tone, lead, children}: {tone: 'info' | 'warning'; lead: string; children: React.ReactNode}) {
  const Icon = tone === 'warning' ? WarningIcon : InfoIcon;
  return (
    <div
      className={cx(
        'flex gap-2.5 rounded-lg border px-3.5 py-3 text-[13px] leading-[1.5] text-text',
        tone === 'warning' ? 'border-warning-soft bg-warning-soft' : 'border-accent-border bg-accent-soft'
      )}>
      <Icon className={cx('mt-px h-4 w-4 flex-none', tone === 'warning' ? 'text-warning' : 'text-accent-text')} />
      <span>
        <strong className="font-semibold">{lead}</strong> {children}
      </span>
    </div>
  );
}

// ── Sections ────────────────────────────────────────────────────────────────

function SectionHeading({children, id}: {children: React.ReactNode; id?: string}) {
  return (
    <h2
      id={id}
      className="text-sm font-semibold text-text">
      {children}
    </h2>
  );
}

function Tile({label, value, isProblem}: {label: string; value: string; isProblem?: boolean}) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2.5">
      <p className="text-xs text-text-2">{label}</p>
      <p className={cx('mt-0.5 text-lg font-semibold', isProblem ? 'text-danger' : 'text-text')}>{value}</p>
    </div>
  );
}

function SummaryTiles({report}: {report: DataQualityReport}) {
  const duplicates = report.exact.duplicateRows;
  const columnsWithIssues = report.exact.columns.filter((c) => isTypedColumn(c) && c.nonParsingValues > 0).length;

  return (
    // 2×2 on a phone, 4-up from tablet. A 4-wide row of numbers on a 375px screen
    // shrinks each one past the point of being readable.
    <div className="grid grid-cols-2 gap-3 tablet:grid-cols-4">
      <Tile
        label="Rows"
        value={formatCount(report.exact.rowCount)}
      />
      <Tile
        label={report.fileCount === 1 ? 'File' : 'Files'}
        value={formatCount(report.fileCount)}
      />
      <Tile
        label="Duplicate rows"
        value={typeof duplicates === 'number' ? formatCount(duplicates) : 'Not computed'}
        isProblem={typeof duplicates === 'number' && duplicates > 0}
      />
      <Tile
        label="Columns with issues"
        value={formatCount(columnsWithIssues)}
        isProblem={columnsWithIssues > 0}
      />
    </div>
  );
}

function TopIssues({issues}: {issues: string[]}) {
  if (issues.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>What to look at first</SectionHeading>
      <ul className="flex flex-col gap-2">
        {issues.map((issue) => {
          const approximate = isApproximateIssue(issue);
          return (
            <li
              key={issue}
              className="flex items-start gap-3 rounded-lg border border-border bg-surface p-3">
              <WarningIcon className="mt-0.5 h-4 w-4 flex-none text-warning" />
              <p className="min-w-0 flex-1 break-words text-sm text-text">{issue}</p>
              <StatusChip
                label={approximate ? 'Approximate' : 'Exact'}
                tone={approximate ? 'warning' : 'danger'}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── Where the figures are ───────────────────────────────────────────────────

/**
 * The three sentences beneath the two new sections.
 *
 * `SAMPLES_TRUNCATION_NOTE`'s 200 is `report.py::MAX_SAMPLE_VALUE_CHARS` and
 * `SAMPLES_COUNTING_NOTE` exists because the tile above counts every copy after the first while
 * these counts include it — two numbers from one figure, which a reader would otherwise reconcile
 * by assuming one of them is wrong. `lambdas/test_data_quality_report_contract.py` holds the 200
 * against the plane's constant, because a note stating a figure no report produces is worse than
 * no note.
 */
export const SAMPLES_TRUNCATION_NOTE = 'Values longer than 200 characters are shortened.';
export const SAMPLES_COUNTING_NOTE = 'Duplicate rows counts every copy after the first.';
export const ENCODING_EXAMPLES_NOTE = 'These are the first examples found, not all of them.';

/** Why a list stops short of what the report found — the one reason the writer ever has. */
const TOO_LARGE_TO_LIST = 'because the report would have been too large to open';

/** `one` for exactly one, `many` otherwise — the count itself is formatted by the caller. */
function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

/**
 * How many rows each file holds, on request.
 *
 * The report has always stored this and never shown it, so a folder whose row count looks wrong
 * gave no way to find which file was wrong. A `<details>` rather than a section: it is one line
 * closed, and a folder of two hundred files would otherwise push every finding below the fold.
 *
 * Withheld below two files, because a single-file report's one count IS the report's row count
 * and a disclosure repeating it reads as a second, different figure. An empty array takes the same
 * branch, so a report whose per-file counts never arrived renders nothing rather than an empty table.
 * The files the report left out count toward the two and the summary's total, and are named in a
 * line of their own rather than as rows.
 */
function RowsPerFileDisclosure({
  location,
  entries,
  unlisted
}: {
  location: string;
  entries: {key: string; rows: number}[];
  unlisted: number;
}) {
  const root = sourceFolderPrefix(location);
  const total = entries.length + unlisted;
  if (total < 2) return null;
  return (
    <details className="rounded-lg border border-border bg-surface">
      <summary className="cursor-pointer px-3 py-2 text-sm font-semibold text-text">
        Rows in each file ({formatCount(total)} files)
      </summary>
      {/* No scroll container: two columns, the path already wraps on `break-all`, so there is
          nothing to scroll — and an `overflow-x-auto` that never scrolls is a pointer-only
          region waiting to happen the first time a column is added. */}
      <div className="px-3 pb-3">
        {entries.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-text-2">
                <th
                  scope="col"
                  className="py-1.5 text-left font-semibold">
                  File
                </th>
                <th
                  scope="col"
                  className="py-1.5 text-right font-semibold">
                  Rows
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr
                  key={entry.key}
                  className="border-b border-border-2 last:border-b-0">
                  <td className="break-all py-1.5 pr-4 font-mono text-text">{relativePath(entry.key, root)}</td>
                  <td className="py-1.5 text-right tabular-nums text-text-2">{formatCount(entry.rows)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {unlisted > 0 && (
          <p className="pt-2 text-sm text-text-2">
            {formatCount(unlisted)} {entries.length > 0 && 'more '}
            {plural(unlisted, 'file isn’t', 'files aren’t')} listed, {TOO_LARGE_TO_LIST}.
          </p>
        )}
      </div>
    </details>
  );
}

/**
 * One duplicate-sample cell.
 *
 * NULL and the empty string are told apart, and both are rendered as TEXT rather than as an empty
 * cell, exactly as the Data Explorer's `CellValue` does — the markers are imported from it rather
 * than re-spelled, because a second copy would drift and the two surfaces would name the same
 * absence differently.
 */
function SampleCell({value}: {value: string | null}) {
  if (value === null || value === '') {
    return <span className="italic text-text-3">{value === null ? NULL_DISPLAY : EMPTY_DISPLAY}</span>;
  }
  return <span className="break-all font-mono">{value}</span>;
}

/**
 * The most-repeated rows, when the check kept any.
 *
 * The count tile answers "how many duplicates"; this answers "which rows", which is the question a
 * tester actually asked. Its columns are the GROUPING's column list, carried on the figure itself
 * rather than taken from `exact.columns` — the two differ on a CSV whose header names a partition,
 * and reading the wrong one would put every value under its neighbour's header.
 *
 * The scroll container is focusable and labelled, because a table wider than the page is otherwise
 * unreachable without a pointer. `columns` can be two hundred entries, and nothing here caps it:
 * the row cap is `DQ_DUPLICATE_SAMPLE` and the width is the user's own schema.
 */
function DuplicateSamplesSection({samples}: {samples: DuplicateSamples | undefined}) {
  const headingId = useId();
  if (!samples) return null;

  // Neither `isReport` nor the type system can promise this field's shape: the document is fetched
  // JSON, and this render path was added after `isReport` chose the fields it validates. So the
  // two arms are tested FOR rather than assumed, and anything else renders nothing.
  if (typeof samples !== 'object') return null;
  if ('omitted' in samples) {
    return (
      <section className="flex flex-col gap-2">
        <SectionHeading>Most repeated rows</SectionHeading>
        <Callout
          tone="info"
          lead="Not shown.">
          {asSentence(samples.omitted)}
        </Callout>
      </section>
    );
  }

  if (!Array.isArray(samples.columns) || !Array.isArray(samples.rows)) return null;
  // Each ROW is checked too, not just the two containers. A row that is null or a string reaches
  // `row.repeats` and `row.values[...]` and throws, which is the same blank screen the container
  // checks exist to avoid — a guard that validates the box and not what is in it.
  const rows = samples.rows.filter(
    (row): row is DuplicateSampleRow => !!row && typeof row === 'object' && Array.isArray(row.values)
  );
  if (rows.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading id={headingId}>Most repeated rows</SectionHeading>
      <p className="text-xs text-text-2">{SAMPLES_COUNTING_NOTE}</p>
      <div
        role="region"
        aria-labelledby={headingId}
        tabIndex={0}
        className="overflow-x-auto rounded-lg border border-border bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <table
          aria-labelledby={headingId}
          className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-2 text-xs text-text-2">
              <th
                scope="col"
                className="whitespace-nowrap px-3 py-2 text-left font-semibold">
                Times it appears
              </th>
              {samples.columns.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="whitespace-nowrap px-3 py-2 text-left font-semibold">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                // The rows are a bag of user values with no identifier of their own, and two
                // groups can differ only in a column that is null in both renderings.
                key={index}
                className="border-b border-border-2 text-text last:border-b-0">
                <td className="px-3 py-2 text-left font-medium tabular-nums">
                  {typeof row.repeats === 'number' ? formatCount(row.repeats) : ''}
                </td>
                {samples.columns.map((column, cell) => (
                  <td
                    key={column}
                    className="px-3 py-2 align-top">
                    <SampleCell value={row.values[cell] ?? null} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-text-3">{SAMPLES_TRUNCATION_NOTE}</p>
    </section>
  );
}

// ── Columns ─────────────────────────────────────────────────────────────────

function columnIssueCount(column: ColumnFinding): number {
  return isTypedColumn(column) ? column.nonParsingValues : 0;
}

function ColumnTypeCell({column}: {column: ColumnFinding}) {
  if (!isTypedColumn(column)) {
    // A skipped check is NEVER a clean pass — it renders as its own state with the
    // reason attached, not as a blank that reads like "nothing wrong here".
    return (
      <div className="flex flex-col gap-1">
        <StatusChip
          label="Skipped"
          tone="warning"
        />
        <span className="text-xs text-text-2">{asSentence(column.reason)}</span>
      </div>
    );
  }
  return <span className="text-text-2">{dominantTypeLabel(column.dominantType)}</span>;
}

function ColumnSamples({column}: {column: ColumnFinding}) {
  if (!isTypedColumn(column) || column.sampleOffending.length === 0) return null;
  return (
    <p className="mt-1 break-words font-mono text-xs text-text-3">
      e.g. {column.sampleOffending.slice(0, 5).join(', ')}
    </p>
  );
}

/**
 * A disclosure, not a finding: the other spellings merged into this one column, which Athena reads as one.
 * Any the report left out are counted after the ones it kept, or alone when it kept none.
 */
function ColumnSpellings({column}: {column: ColumnFinding}) {
  const listed = column.otherSpellings ?? [];
  const unlisted = column.otherSpellingsUnlisted ?? 0;
  if (listed.length === 0 && unlisted === 0) return null;
  const ways = plural(unlisted, 'way', 'ways');
  return (
    <p className="mt-0.5 break-words text-xs text-text-3">
      {listed.length > 0 ? (
        <>
          Also spelled <span className="break-all font-mono">{listed.join(', ')}</span> in other files
          {unlisted > 0 && `, and ${formatCount(unlisted)} more ${ways} not listed, ${TOO_LARGE_TO_LIST}`}
        </>
      ) : (
        `Also spelled ${formatCount(unlisted)} other ${ways} in other files, not listed, ${TOO_LARGE_TO_LIST}`
      )}
    </p>
  );
}

/**
 * One sentence per column named after a partition, saying where its figures went. Without it a
 * CSV's `Year` shows up as an unfamiliar `year_in_file`, and a JSON or Parquet one is simply
 * missing from Columns, with nothing on the page to say why.
 */
function PartitionNamedNotes({entries}: {entries: PartitionNamedColumn[]}) {
  if (entries.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1 text-sm text-text-2">
      {entries.map((entry) => (
        <li key={entry.name}>
          <span className="break-all font-mono font-medium text-text">{entry.name}</span>
          {entry.outcome === 'renamed' ? (
            <>
              {' '}
              is listed as <span className="break-all font-mono font-medium text-text">{entry.as}</span>. The folder has
              a partition of the same name, and a CSV’s columns are read in order, so the file’s own column keeps its
              values under a new name.
            </>
          ) : (
            <>
              {' '}
              has no figures here. The folder has a partition of the same name, and a table over this folder reads the
              partition’s value in its place.
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

function ColumnsSection({columns, partitionNamed}: {columns: ColumnFinding[]; partitionNamed: PartitionNamedColumn[]}) {
  // Mount-gated, not CSS-hidden: the two presentations are
  // structurally different DOM — a faux-table of rows versus a list of cards — so a
  // CSS swap would put BOTH in the document, doubling every column of a 200-column
  // report and reading each one twice to a screen reader.
  const isMobile = useIsMobile();

  if (columns.length === 0 && partitionNamed.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>Columns</SectionHeading>
      <PartitionNamedNotes entries={partitionNamed} />
      {isMobile ? (
        <ul className="flex flex-col gap-2">
          {columns.map((column) => (
            <li
              key={column.name}
              className={cx(
                'rounded-lg border border-border p-3',
                columnIssueCount(column) > 0 ? 'bg-danger-soft' : 'bg-surface'
              )}>
              <p className="break-all font-mono text-sm font-semibold text-text">{column.name}</p>
              <ColumnSpellings column={column} />
              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                <span className="text-text-2">
                  Null or blank <span className="font-medium text-text">{formatRatio(column.nullBlankRatio)}</span>
                </span>
                {isTypedColumn(column) && (
                  <span className="text-text-2">
                    Doesn’t fit{' '}
                    <span className={cx('font-medium', column.nonParsingValues > 0 ? 'text-danger' : 'text-text')}>
                      {formatCount(column.nonParsingValues)}
                    </span>
                  </span>
                )}
              </div>
              <div className="mt-1.5 text-xs">
                <ColumnTypeCell column={column} />
              </div>
              <ColumnSamples column={column} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          {/* Decorative header strip — the row content below is self-labelling, and a
              real <table> would fight the wrapping the samples column needs. */}
          <div
            aria-hidden="true"
            className="flex gap-4 border-b border-border bg-surface-2 px-4 py-2 text-xs font-semibold text-text-2">
            <span className="flex-1">Column</span>
            <span className="w-40">Type</span>
            <span className="w-32 text-right">Doesn’t fit</span>
            <span className="w-28 text-right">Null or blank</span>
          </div>
          <ul>
            {columns.map((column) => {
              const issues = columnIssueCount(column);
              return (
                <li
                  key={column.name}
                  className={cx(
                    'flex gap-4 border-b border-border-2 px-4 py-2.5 text-sm last:border-b-0',
                    // Tint AND a bold count — the tint is never the only signal.
                    issues > 0 && 'bg-danger-soft'
                  )}>
                  <div className="min-w-0 flex-1">
                    <span className="break-all font-mono text-text">{column.name}</span>
                    <ColumnSpellings column={column} />
                    <ColumnSamples column={column} />
                  </div>
                  <div className="w-40 text-xs">
                    <ColumnTypeCell column={column} />
                  </div>
                  {/* The header strip above is hidden from assistive technology, so each figure
                      carries its own column name or it is read as a bare number. */}
                  <span className={cx('w-32 text-right', issues > 0 ? 'font-medium text-danger' : 'text-text-2')}>
                    <span className="sr-only">Doesn’t fit </span>
                    {isTypedColumn(column) ? formatCount(issues) : '—'}
                  </span>
                  <span className="w-28 text-right text-text-2">
                    <span className="sr-only">Null or blank </span>
                    {formatRatio(column.nullBlankRatio)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

// ── Cross-file agreement ────────────────────────────────────────────────────

function CrossFileSection({
  columnsAgree,
  disagreements,
  unlisted
}: {
  columnsAgree: boolean;
  disagreements: CrossFileDisagreement[];
  unlisted: number;
}) {
  if (columnsAgree) return null;
  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>Files that disagree about their columns</SectionHeading>
      {disagreements.length > 0 && (
        <ul className="flex flex-col gap-2">
          {disagreements.map((d) => (
            <li
              key={d.file}
              className="rounded-lg border border-border bg-danger-soft p-3 text-sm">
              <p className="break-all font-mono font-semibold text-text">{d.file}</p>
              {d.missing.length > 0 && (
                <p className="mt-1 text-text-2">
                  Missing: <span className="font-medium text-text">{d.missing.join(', ')}</span>
                </p>
              )}
              {d.extra.length > 0 && (
                <p className="mt-1 text-text-2">
                  Extra: <span className="font-medium text-text">{d.extra.join(', ')}</span>
                </p>
              )}
              {d.shifted && (
                <p className="mt-1 text-text-2">
                  Positions: <span className="font-medium text-text">don’t line up with this report’s Columns</span>. A
                  CSV is read by position, so this file’s values are counted under the wrong columns.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {unlisted > 0 && (
        <p className="text-sm text-text-2">
          {formatCount(unlisted)} {disagreements.length > 0 && 'more '}
          {plural(unlisted, 'file disagrees about its', 'files disagree about their')} columns but{' '}
          {plural(unlisted, 'isn’t', 'aren’t')} listed, {TOO_LARGE_TO_LIST}.
        </p>
      )}
    </section>
  );
}

// ── Approximate figures ─────────────────────────────────────────────────────

/**
 * Where the invalid text encoding actually is.
 *
 * The byte scan has always recorded these and the page has never shown them, so a report saying
 * "4 invalid text encodings" gave a user nothing to open. Each example is the object's path
 * relative to the checked folder plus the byte offset inside it, which is what makes it findable.
 *
 * Only rendered beside a non-zero count: a measured figure of zero with a stale example list
 * would read as a contradiction, and the scan caps the list at `DQ_OFFSET_SAMPLE` regardless.
 */
function EncodingExamples({
  location,
  figure
}: {
  location: string;
  figure: Extract<EncodingFigure, {invalidUtf8Sequences: number}>;
}) {
  const root = sourceFolderPrefix(location);
  // Both reads are defaulted rather than trusted. `isReport` validates the fields every render
  // path indexed into when it was written and neither of these was one of them, so a document
  // missing one would throw mid-render — a blank screen where the service has a refusal ready.
  const examples = figure.sampleOffsets ?? [];
  if (figure.invalidUtf8Sequences === 0 || examples.length === 0) return null;
  return (
    <Callout
      tone="info"
      lead="Examples:">
      <ul className="mt-1 flex flex-col gap-0.5">
        {examples.map((example) => (
          <li
            key={`${example.key}:${example.offset}`}
            className="break-all font-mono text-xs">
            {relativePath(example.key, root)}, byte {formatCount(example.offset)}
          </li>
        ))}
      </ul>
      <span className="mt-1 block">{ENCODING_EXAMPLES_NOTE}</span>
    </Callout>
  );
}

/**
 * The ragged-row and encoding figures — the two the report files under `approximate`.
 *
 * EVERY branch here emits a qualifier beside its number. The Lambda's own `note` is
 * rendered verbatim where it exists (it already states both ragged over-counting causes
 * and the encoding coverage percentage), with a fallback sentence if a report somehow
 * arrives without one: a bare number with no qualifier is the failure mode this whole
 * section exists to prevent.
 */
function ApproximateSection({
  location,
  ragged,
  encoding
}: {
  /** The checked location, which the encoding examples are spelled relative to. */
  location: string;
  ragged: RaggedRowsFigure;
  encoding: EncodingFigure;
}) {
  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>Estimated figures</SectionHeading>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3">
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm font-medium text-text">Rows with the wrong number of fields</p>
          {isUnmeasured(ragged) ? (
            <StatusChip
              label={isSkipped(ragged) ? 'Skipped' : 'Not computed'}
              tone="warning"
            />
          ) : (
            <StatusChip
              label="Approximate"
              tone="warning"
            />
          )}
        </div>
        {isUnmeasured(ragged) ? (
          <Callout
            tone="info"
            lead={isSkipped(ragged) ? 'Not applicable.' : 'Not computed.'}>
            {asSentence(ragged.reason)}
          </Callout>
        ) : (
          <>
            <p className="text-lg font-semibold text-text">{formatCount(ragged.count)}</p>
            {/* The lead COMPLEMENTS the Lambda's note rather than repeating it: that note
                already opens with its own "Approximate — " label, and a lead saying the
                same thing reads as a stutter. The note itself is rendered verbatim. */}
            <Callout
              tone="warning"
              lead="What this counts.">
              {ragged.note ||
                'Approximate — over-counts rows with commas inside quotes, and rows with newlines inside quoted fields.'}
            </Callout>
          </>
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3">
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm font-medium text-text">Invalid text encoding</p>
          {isUnmeasured(encoding) ? (
            <StatusChip
              label={isSkipped(encoding) ? 'Skipped' : 'Not computed'}
              tone="warning"
            />
          ) : (
            <StatusChip
              label={encoding.coverage === 'complete' ? 'Exact' : 'Sampled'}
              tone={encoding.coverage === 'complete' ? 'success' : 'warning'}
            />
          )}
        </div>
        {isUnmeasured(encoding) ? (
          <Callout
            tone="info"
            lead={isSkipped(encoding) ? 'Not applicable.' : 'Not computed.'}>
            {asSentence(encoding.reason)}
          </Callout>
        ) : (
          <>
            <p className="text-lg font-semibold text-text">{formatCount(encoding.invalidUtf8Sequences)}</p>
            {/* Same reason as above: the note opens with "Sampled — " / "Complete — ",
                so the lead names the dimension instead of restating the label. */}
            <Callout
              tone={encoding.coverage === 'complete' ? 'info' : 'warning'}
              lead="Coverage.">
              {encoding.note || `${encoding.coveragePercent}% of bytes examined.`}
            </Callout>
            <EncodingExamples
              location={location}
              figure={encoding}
            />
          </>
        )}
      </div>
    </section>
  );
}

// ── The page ────────────────────────────────────────────────────────────────

/**
 * The read-only data-quality report view (`/data-quality/:space/:requestId`).
 *
 * The space is IN THE ROUTE and not derived, because the report lives at
 * `{space}/_data-quality-reports/{requestId}/report.json` and the request id alone does
 * not say which space holds it. A `/data-quality/:requestId` route could not locate a
 * shared-space report at all, so the deep link would land on a permanent
 * not-found for exactly the reports that are hardest to find another way.
 *
 * Everything on this page reads; nothing mutates. The two header actions are the
 * exceptions the page is built around — and neither changes the data being reported on.
 */
export function DataQualityReportPage() {
  const {space: spaceName = '', requestId = ''} = useParams<{space: string; requestId: string}>();
  const navigate = useNavigate();
  usePageTitle('Data quality report');

  const {report, space, isLoading, error, refreshError, isInaccessible} = useDataQualityReport(spaceName, requestId);
  const {start, isPending} = useDataQualityCheck();

  const handleRerun = async () => {
    if (!space || !report) return;
    // Deliberately does NOT navigate: the report on screen stays readable while the new
    // check runs, and the new one arrives by notification like any other.
    await start({space, location: report.location});
  };

  // `?space=` takes the CONNECTION id, which is the literal 'personal' for a personal
  // space — not the username, which is what `:space` in this route is.
  const folderHref =
    report && space
      ? `/files?space=${encodeURIComponent(space.kind === 'personal' ? 'personal' : spaceName)}&prefix=${encodeURIComponent(sourceFolderPrefix(report.location))}`
      : undefined;
  // Leaves for the file browser, so it follows the destination's flags.
  const canOpenFolder = useCanFollowLink()(folderHref ?? '/files');

  const actions = report ? (
    <>
      <Button
        variant="default"
        onClick={handleRerun}
        disabled={isPending}
        disabledReason={space ? (rerunRefusal(report.location, space.prefix) ?? undefined) : undefined}>
        {isPending ? 'Starting…' : 'Re-run check'}
      </Button>
      {folderHref && canOpenFolder && (
        <Button
          variant="default"
          onClick={() => navigate(folderHref)}>
          Open folder
        </Button>
      )}
    </>
  ) : undefined;

  return (
    <PageLayout
      title="Data quality report"
      subtitle={report ? <span className="break-all font-mono">{report.location}</span> : undefined}
      contentClassName="max-w-[920px] gap-4"
      stackActionsOnMobile
      actions={actions}>
      {isLoading && (
        <p
          role="status"
          className="text-sm text-text-2">
          Loading report…
        </p>
      )}

      {/* An inaccessible space and a nonexistent one render IDENTICALLY, and neither
          issues a request. Anything else would turn this page into an oracle for
          which shared spaces exist. */}
      {!isLoading && isInaccessible && (
        <Banner
          variant="warning"
          title="Report not available">
          This report isn’t available. It may have been deleted, or it may belong to a space you no longer have access
          to.
        </Banner>
      )}

      {!isLoading && !isInaccessible && error && (
        <Banner
          variant="warning"
          title="Report not available">
          {error}
        </Banner>
      )}

      {report && (
        <>
          {refreshError && (
            <Banner
              variant="warning"
              title="Couldn’t refresh this report">
              This is the copy loaded earlier. {refreshError}
            </Banner>
          )}

          <Banner
            variant={report.verdict === 'clean' && !report.hasIncompleteFigures ? 'success' : 'warning'}
            role="status"
            title={
              report.verdict === 'clean'
                ? report.hasIncompleteFigures
                  ? 'No issues found in what could be checked'
                  : 'No issues found'
                : 'Issues found'
            }>
            {/* Two qualifiers off two different flags. hasApproximateFigures is true on
                every report this arc produces, so it can only ever say something soft —
                a warning keyed to it would fire on a spotless CSV and be learned as
                noise. hasIncompleteFigures is the one that varies, so it warns. */}
            {report.hasIncompleteFigures && (
              <p>Some checks couldn’t be completed on this data — the details below say which, and why.</p>
            )}
            {report.hasApproximateFigures && (
              <p className={report.hasIncompleteFigures ? 'mt-1' : undefined}>
                Some figures are estimates rather than exact counts. Each one says so where it appears.
              </p>
            )}
          </Banner>

          <SummaryTiles report={report} />
          <TopIssues issues={report.topIssues} />
          <RowsPerFileDisclosure
            location={report.location}
            entries={report.exact.rowCountsByFile ?? []}
            unlisted={report.exact.rowCountsByFileUnlisted ?? 0}
          />
          <DuplicateSamplesSection samples={report.exact.duplicateSamples} />
          <CrossFileSection
            columnsAgree={report.exact.crossFile.columnsAgree}
            disagreements={report.exact.crossFile.disagreements}
            unlisted={report.exact.crossFile.disagreementsUnlisted ?? 0}
          />
          <ColumnsSection
            columns={report.exact.columns}
            partitionNamed={report.partitionNamedColumns ?? []}
          />
          <ApproximateSection
            location={report.location}
            ragged={report.approximate.raggedRows}
            encoding={report.approximate.encoding}
          />

          <footer className="border-t border-border pt-3 text-xs text-text-3">
            <p>
              Checked {report.fileCount} {report.fileCount === 1 ? 'file' : 'files'}
              {report.completedAt ? ` on ${formatTimestamp(report.completedAt)}` : ''}. Format: {report.format}.
            </p>
            <p className="mt-1">This check only read your data. Nothing was modified, moved, or deleted.</p>
          </footer>
        </>
      )}
    </PageLayout>
  );
}
