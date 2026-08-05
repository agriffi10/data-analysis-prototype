import {useParams, useNavigate} from 'react-router';
import {PageLayout} from '../../components/PageLayout';
import {Banner} from '../../components/Banner';
import {Button} from '../../components/Button';
import {WarningIcon, InfoIcon} from '../../components/icons';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useIsMobile} from '../../lib/useBreakpoint';
import {cx} from '../../lib/cx';
import {formatCount} from '../query/query.format';
import {useDataQualityReport} from './useDataQualityReport';
import {useDataQualityCheck} from './useDataQualityCheck';
import {
  asSentence,
  dominantTypeLabel,
  formatRatio,
  formatTimestamp,
  isApproximateIssue,
  sourceFolderPrefix
} from './dataQuality.format';
import {isTypedColumn, isUnmeasured, isSkipped} from './dataQuality.types';
import type {
  ColumnFinding,
  CrossFileDisagreement,
  DataQualityReport,
  EncodingFigure,
  RaggedRowsFigure
} from './dataQuality.types';

// ── Chips ───────────────────────────────────────────────────────────────────

type ChipTone = 'danger' | 'warning' | 'success';
type ChipLabel = 'Exact' | 'Approximate' | 'Sampled' | 'Skipped' | 'Not computed';

const CHIP_TONES: Record<ChipTone, string> = {
  danger: 'bg-danger-soft text-danger',
  warning: 'bg-warning-soft text-warning',
  success: 'bg-success-soft text-success'
};

/**
 * The `ConnectionsPage` StatusBadge shape, reused rather than reinvented: a dot PLUS a
 * text label, never colour alone. The label is what carries the meaning — the tone is
 * decoration, and a user who cannot distinguish the tones loses nothing.
 */
function StatusChip({label, tone}: {label: ChipLabel; tone: ChipTone}) {
  return (
    <span
      className={cx(
        'inline-flex flex-none items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold',
        CHIP_TONES[tone]
      )}>
      <span
        aria-hidden="true"
        className="h-[7px] w-[7px] rounded-full bg-current"
      />
      {label}
    </span>
  );
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

function SectionHeading({children}: {children: React.ReactNode}) {
  return <h2 className="text-sm font-semibold text-text">{children}</h2>;
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

function ColumnsSection({columns}: {columns: ColumnFinding[]}) {
  // Mount-gated, not CSS-hidden (SPEC-099 precedent): the two presentations are
  // structurally different DOM — a faux-table of rows versus a list of cards — so a
  // CSS swap would put BOTH in the document, doubling every column of a 200-column
  // report and reading each one twice to a screen reader.
  const isMobile = useIsMobile();

  if (columns.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>Columns</SectionHeading>
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
                    <ColumnSamples column={column} />
                  </div>
                  <div className="w-40 text-xs">
                    <ColumnTypeCell column={column} />
                  </div>
                  <span className={cx('w-32 text-right', issues > 0 ? 'font-medium text-danger' : 'text-text-2')}>
                    {isTypedColumn(column) ? formatCount(issues) : '—'}
                  </span>
                  <span className="w-28 text-right text-text-2">{formatRatio(column.nullBlankRatio)}</span>
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
  disagreements
}: {
  columnsAgree: boolean;
  disagreements: CrossFileDisagreement[];
}) {
  if (columnsAgree) return null;
  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>Files that disagree about their columns</SectionHeading>
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
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Approximate figures ─────────────────────────────────────────────────────

/**
 * The ragged-row and encoding figures — the two the report files under `approximate`.
 *
 * EVERY branch here emits a qualifier beside its number. The Lambda's own `note` is
 * rendered verbatim where it exists (it already states both ragged over-counting causes
 * and the encoding coverage percentage), with a fallback sentence if a report somehow
 * arrives without one: a bare number with no qualifier is the failure mode this whole
 * section exists to prevent.
 */
function ApproximateSection({ragged, encoding}: {ragged: RaggedRowsFigure; encoding: EncodingFigure}) {
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
 * shared-space report at all, so SPEC-114's deep link would land on a permanent
 * not-found for exactly the reports that are hardest to find another way.
 *
 * Everything on this page reads; nothing mutates. The two header actions are the
 * exceptions the page is built around — and neither changes the data being reported on.
 */
export function DataQualityReportPage() {
  const {space: spaceName = '', requestId = ''} = useParams<{space: string; requestId: string}>();
  const navigate = useNavigate();
  usePageTitle('Data quality report');

  const {report, space, isLoading, error, isInaccessible} = useDataQualityReport(spaceName, requestId);
  const {start, isPending} = useDataQualityCheck();

  const handleRerun = async () => {
    if (!space || !report) return;
    // Deliberately does NOT navigate: the report on screen stays readable while the new
    // check runs, and the new one arrives by notification like any other.
    await start({space, location: report.location});
  };

  const handleOpenFolder = () => {
    if (!report || !space) return;
    // `?space=` takes the CONNECTION id, which is the literal 'personal' for a personal
    // space — not the username, which is what `:space` in this route is.
    const spaceParam = space.kind === 'personal' ? 'personal' : spaceName;
    navigate(
      `/files?space=${encodeURIComponent(spaceParam)}&prefix=${encodeURIComponent(sourceFolderPrefix(report.location))}`
    );
  };

  const actions = report ? (
    <>
      <Button
        variant="default"
        onClick={handleRerun}
        disabled={isPending}>
        {isPending ? 'Starting…' : 'Re-run check'}
      </Button>
      <Button
        variant="default"
        onClick={handleOpenFolder}>
        Open folder
      </Button>
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
          <CrossFileSection
            columnsAgree={report.exact.crossFile.columnsAgree}
            disagreements={report.exact.crossFile.disagreements}
          />
          <ColumnsSection columns={report.exact.columns} />
          <ApproximateSection
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
