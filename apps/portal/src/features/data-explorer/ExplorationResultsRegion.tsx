import {useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {ErrorBanner} from '../../components/ErrorBanner';
import {Pager} from '../../components/Pager';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useQueryResults} from '../catalog/useQueryResults';
import {EXPLORATION_PAGE_SIZE} from './dataExplorer.constants';
import {ColumnsPanel} from './ColumnsPanel';
import {ExplorationGrid} from './ExplorationGrid';
import {ExplorationRecordView} from './ExplorationRecordView';
import {ExplorationTextView} from './ExplorationTextView';
import {PresentationSwitch} from './PresentationSwitch';
import {ValuePanel} from './ValuePanel';
import {useCellSelection} from './useCellSelection';
import {useColumnGeometry} from './useColumnGeometry';
import type {QueryColumn} from '../catalog/catalog.types';
import type {ExplorationPresentation, GridPresentation} from './dataExplorer.types';

export type ExplorationResultsRegionProps = {
  queryExecutionId: string | null;
  /** The exploration is starting or still running. */
  isPending: boolean;
  /** A render refusal, a failed start, or a failed poll. Rendered through `toUserMessage`. */
  error: unknown;
  /**
   * Columns the SOURCE is known to have before any execution returns — Glue's, for a
   * `table` source. Empty for a `sql` source, whose columns are unknowable until the
   * first execution reports them (FR-006).
   */
  schemaColumns: QueryColumn[];
  /** The active tab's presentation state — the grid's geometry lives here. */
  presentation: ExplorationPresentation;
  onPresentationChange: (update: (presentation: ExplorationPresentation) => ExplorationPresentation) => void;
};

/**
 * One exploration's rows: the toolbar, the chosen presentation, the Value panel and the
 * pager (SPEC-180).
 *
 * Owns the page, the geometry and the selection so the three views below stay
 * presentational. Paging goes through SPEC-176's `useQueryResults`, whose `NextToken` walk
 * scans no additional bytes — and neither does anything in the toolbar, because none of it
 * renders SQL.
 *
 * Errors go through `ErrorBanner` (SPEC-106): Athena's own text never reaches a user, and
 * neither does an `ExplorationRenderError`, whose message names a column for an operator.
 */
export function ExplorationResultsRegion({
  queryExecutionId,
  isPending,
  error,
  schemaColumns,
  presentation,
  onPresentationChange
}: ExplorationResultsRegionProps) {
  const results = useQueryResults(queryExecutionId, EXPLORATION_PAGE_SIZE);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const gridRef = useRef<HTMLTableElement>(null);
  // FR-006: a `table` source knows its columns from Glue before anything runs, a `sql`
  // source only from the execution. The execution's own metadata WINS once it lands —
  // grouping changes the column set entirely, and Glue would still be describing the
  // table underneath it.
  const columns = results.columns.length > 0 ? results.columns : schemaColumns;
  const geometry = useColumnGeometry(columns, presentation, onPresentationChange);
  const visibleNames = geometry.visible.map((column) => column.name);
  // Paging clears the selection rather than carrying coordinates onto different rows
  // (FR-002 AC8), and so does a change to the column set — a row/column pair means
  // nothing once either axis has moved underneath it.
  const selection = useCellSelection(
    results.rows.length,
    visibleNames,
    `${queryExecutionId ?? ''}:${results.pageIndex}:${visibleNames.join(' ')}`,
    gridRef
  );

  // FR-007: below `tablet` an UNCHOSEN tab opens in Record — a horizontally-scrolling grid
  // on a 400px screen is not a data explorer. `useIsMobile` decides which view MOUNTS,
  // never how anything is styled (SPEC-095 FR-008), and a tab whose user HAS chosen keeps
  // that choice at every width, which is what `presentation: null` exists to express.
  const isMobile = useIsMobile();
  const view: GridPresentation = presentation.presentation ?? (isMobile ? 'record' : 'grid');

  // The stored row outlives the page it was taken on (a tab switch, a restore), so it is
  // clamped where it is READ.
  const recordRow = Math.min(Math.max(presentation.recordRowIndex, 0), Math.max(results.rows.length - 1, 0));

  // Record and the grid share ONE focused row, and the sync runs in BOTH directions —
  // entering Record from the cursor, and moving the cursor to the row Record left off at
  // (FR-004 AC3). Only the first half shipped at first, so "switch back" landed on
  // whatever the cursor last touched (found in review).
  const setView = (next: GridPresentation) => {
    if (next !== 'record' && view === 'record') {
      selection.selectCell({row: recordRow, column: selection.selection.cursor.column}, {});
    }
    onPresentationChange((p) => ({
      ...p,
      presentation: next,
      recordRowIndex: next === 'record' ? selection.selection.cursor.row : p.recordRowIndex
    }));
  };

  const cursorColumn = geometry.visible.find((column) => column.name === selection.selection.cursor.column) ?? null;
  const cursorValue = cursorColumn
    ? results.rows[view === 'record' ? recordRow : selection.selection.cursor.row]?.[cursorColumn.index]
    : undefined;

  if (error) {
    return (
      <div className="p-4">
        <ErrorBanner error={error} />
      </div>
    );
  }

  if (queryExecutionId && results.isError) {
    return (
      <div className="p-4">
        <ErrorBanner error={results.error} />
      </div>
    );
  }

  const loading = isPending || !queryExecutionId || results.isPending;

  // Nothing to draw a header from yet: the statement is running and the source could not
  // say what its columns are. That is the `sql` arm's ordinary state (FR-006 AC2) — and
  // the `table` arm's only while Glue is still being read.
  if (loading && geometry.visible.length === 0) {
    return (
      <p
        role="status"
        className="p-4 text-sm text-text-3">
        {queryExecutionId ? 'Loading rows…' : 'Running…'}
      </p>
    );
  }

  // A query that succeeded over no matching rows is an ANSWER, not a fault — the friendly
  // empty state, never the error banner.
  if (!loading && results.rows.length === 0) {
    return <p className="p-4 text-sm text-text-2">No rows returned.</p>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
      <div className="flex flex-none flex-wrap items-center gap-2">
        <PresentationSwitch
          value={view}
          onChange={setView}
        />
        <Button
          size="sm"
          onClick={() => setColumnsOpen(true)}>
          Columns
        </Button>
        <Button
          size="sm"
          aria-pressed={presentation.valuePanelOpen}
          onClick={() => onPresentationChange((p) => ({...p, valuePanelOpen: !p.valuePanelOpen}))}>
          Value
        </Button>
        {/* The count says "on this page" every time it is said, because that is the only
            thing a selection here can ever mean — Ctrl/Cmd+A included (FR-002 AC4). */}
        <p
          role="status"
          className="text-xs text-text-3">
          {loading
            ? queryExecutionId
              ? 'Loading rows…'
              : 'Running…'
            : selection.selectedCount > 0
              ? `${selection.selectedCount} ${selection.selectedCount === 1 ? 'cell' : 'cells'} selected on this page`
              : ''}
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 tablet:flex-row">
        {view === 'grid' && (
          <ExplorationGrid
            columns={geometry.visible}
            rows={results.rows}
            rangeStart={results.rangeStart}
            geometry={geometry}
            selection={selection}
            gridRef={gridRef}
          />
        )}
        {view === 'record' && (
          <ExplorationRecordView
            columns={geometry.visible}
            rows={results.rows}
            rowIndex={recordRow}
            rangeStart={results.rangeStart}
            onRowIndexChange={(next) => onPresentationChange((p) => ({...p, recordRowIndex: next}))}
            onFocusColumn={(column) => selection.selectCell({row: recordRow, column}, {})}
          />
        )}
        {view === 'text' && (
          <ExplorationTextView
            columns={geometry.visible}
            rows={results.rows}
            rangeStart={results.rangeStart}
            rangeEnd={results.rangeEnd}
          />
        )}

        {presentation.valuePanelOpen && (
          <ValuePanel
            column={cursorColumn?.name ?? null}
            value={cursorValue}
            onClose={() => onPresentationChange((p) => ({...p, valuePanelOpen: false}))}
          />
        )}
      </div>

      <Pager
        hasPrev={results.hasPrev}
        hasNext={results.hasNext}
        onPrev={results.goPrev}
        onNext={results.goNext}
        nextBusy={results.isFetchingNext}
        label={`Rows ${results.rangeStart}–${results.rangeEnd}`}
        className="flex-none px-1"
      />

      <ColumnsPanel
        open={columnsOpen}
        onClose={() => setColumnsOpen(false)}
        geometry={geometry}
      />
    </div>
  );
}
