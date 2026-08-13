import {useMemo, useRef, useState} from 'react';
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
import {ExpressionBar} from './ExpressionBar';
import {FilterHistoryControls} from './FilterHistoryControls';
import {OrderFilterDialog} from './OrderFilterDialog';
import {PresentationSwitch} from './PresentationSwitch';
import {ValuePanel} from './ValuePanel';
import {useCellSelection} from './useCellSelection';
import {useColumnGeometry} from './useColumnGeometry';
import {isBareNumeric} from './renderExplorationSql';
import {
  clearFilter,
  clearSort,
  filterOf,
  filterValueKind,
  operatorTakesValue,
  setFilter,
  setSort,
  sortOf
} from './explorationQueryOps';
import type {ColumnQueryActions} from './ColumnFilterMenu';
import type {QueryColumn} from '../catalog/catalog.types';
import type {ExplorationPresentation, GridPresentation} from './dataExplorer.types';
import type {UseExplorationQueryResult} from './useExplorationQuery';

export type ExplorationResultsRegionProps = {
  queryExecutionId: string | null;
  /** The exploration is starting or still running. */
  isPending: boolean;
  /** A render refusal, a failed start, a failed poll or a failed execution. */
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
  /** The query description and every operation over it (SPEC-181). */
  queryControls: UseExplorationQueryResult;
};

export const NO_CELL_TO_FILTER = 'Select a cell first.';
export const UNFILTERABLE_VALUE = 'This cell’s value can’t be used as a filter on a numeric column.';
export const SUSPENDED_TEXT = 'This set of filters failed last time it ran. Nothing has been run.';

/**
 * One exploration's rows, and everything that changes which rows they are (SPEC-180,
 * SPEC-181).
 *
 * The **query toolbar and the expression bar render whatever the results are doing** —
 * loading, empty, or failed. That is not cosmetic: a failed apply has to leave the user
 * somewhere they can correct it (FR-003 AC4/AC5), and a toolbar that disappears with the
 * rows takes the correction with it.
 *
 * For the same reason a failure keeps the LAST GOOD execution's rows on screen beneath the
 * banner rather than emptying the grid. `useQueryResults` is pointed at that execution
 * while the current one is failed; paging it costs nothing, as paging never does.
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
  onPresentationChange,
  queryControls
}: ExplorationResultsRegionProps) {
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const gridRef = useRef<HTMLTableElement>(null);
  const {query, apply} = queryControls;

  // The last execution whose rows actually arrived. A failed apply falls back to it, so
  // the grid keeps showing something true rather than going blank behind a banner.
  const [lastGoodExecutionId, setLastGoodExecutionId] = useState<string | null>(null);
  const failed = Boolean(error);
  const shownExecutionId = failed ? lastGoodExecutionId : queryExecutionId;

  const results = useQueryResults(shownExecutionId, EXPLORATION_PAGE_SIZE);
  // Recorded during render (React's "adjust state when a prop changes" pattern, as
  // `useCellSelection` and `useQueryResults` do) rather than in an effect: an effect would
  // paint one frame in which a failure had emptied the grid before the fallback arrived.
  if (
    !failed &&
    queryExecutionId !== null &&
    !results.isPending &&
    !results.isError &&
    lastGoodExecutionId !== queryExecutionId
  ) {
    setLastGoodExecutionId(queryExecutionId);
  }

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
    `${shownExecutionId ?? ''}:${results.pageIndex}:${visibleNames.join(' ')}`,
    gridRef
  );

  const typeOf = useMemo(() => new Map(geometry.all.map((column) => [column.name, column.type])), [geometry.all]);
  const valueKindOf = (column: string) => filterValueKind(typeOf.get(column) ?? '');

  // Every per-column gesture goes through ONE object, and every one of them is a single
  // `apply` — so a menu choice is a description change, and a description change is at
  // most one execution (FR-001 AC5).
  const actions: ColumnQueryActions = {
    sortOf: (column) => sortOf(query, column),
    sortCount: query.ordering.length,
    filterOf: (column) => filterOf(query, column),
    valueKindOf,
    sort: (column, direction) => apply({ordering: setSort(query, column, direction).ordering}),
    clearSort: (column) => apply({ordering: clearSort(query, column).ordering}),
    filter: (column, operator, value) =>
      apply({
        filters: setFilter(query, {
          column,
          operator,
          value: operatorTakesValue(operator) ? (value ?? '') : undefined,
          valueKind: valueKindOf(column)
        }).filters
      }),
    clearFilter: (column) => apply({filters: clearFilter(query, column).filters})
  };

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
  const cursorRow = view === 'record' ? recordRow : selection.selection.cursor.row;
  // THE RAW CELL VALUE, never `cellText` and never a formatted rendering (FR-002 AC2): a
  // NULL reads as "NULL" on screen and a transformed URL will not look like its value at
  // all (SPEC-184), and either one as a predicate matches nothing.
  const cursorValue = cursorColumn ? results.rows[cursorRow]?.[cursorColumn.index] : undefined;

  const loading = isPending || !shownExecutionId || results.isPending;
  const hasCell = cursorColumn !== null && cursorValue !== undefined;
  const filterByCellRefusal = !hasCell
    ? NO_CELL_TO_FILTER
    : cursorValue !== null &&
        valueKindOf(cursorColumn.name) === 'number' &&
        !isBareNumeric(cursorValue) /* a numeric column's value is emitted BARE, so one
        the renderer would refuse has to be refused at the gesture instead — the refusal
        it throws is operator text (SPEC-106). */
      ? UNFILTERABLE_VALUE
      : null;

  const filterByCell = () => {
    if (!cursorColumn || cursorValue === undefined) return;
    // A NULL cell is `IS NULL`, not `= ''` (FR-002 AC3). Athena hands every value back as
    // a string, so nothing below this line could tell the two apart.
    if (cursorValue === null) actions.filter(cursorColumn.name, 'isNull');
    else actions.filter(cursorColumn.name, '=', cursorValue);
  };

  const body = () => {
    if (queryControls.suspended) {
      return (
        <div className="flex flex-col items-start gap-2 p-4">
          <p className="text-sm text-text-2">{SUSPENDED_TEXT}</p>
          <Button onClick={queryControls.retry}>Run it anyway</Button>
        </div>
      );
    }
    // The banner above has already said this; an empty grid under it would be a second,
    // less true account of the same failure.
    if (shownExecutionId !== null && results.isError) return null;
    // Nothing to draw a header from yet: the statement is running and the source could not
    // say what its columns are. That is the `sql` arm's ordinary state (FR-006 AC2) — and
    // the `table` arm's only while Glue is still being read.
    if (loading && geometry.visible.length === 0) {
      // No `role="status"` here: the toolbar's own status line says the same words at
      // the same moment, and two live regions announcing one event read it out twice.
      return <p className="p-4 text-sm text-text-3">{shownExecutionId ? 'Loading rows…' : 'Running…'}</p>;
    }
    // A query that succeeded over no matching rows is an ANSWER, not a fault — the
    // friendly empty state, never the error banner.
    if (!loading && results.rows.length === 0) return <p className="p-4 text-sm text-text-2">No rows returned.</p>;

    return (
      <>
        <div className="flex min-h-0 flex-1 flex-col gap-2 tablet:flex-row">
          {view === 'grid' && (
            <ExplorationGrid
              columns={geometry.visible}
              rows={results.rows}
              rangeStart={results.rangeStart}
              geometry={geometry}
              selection={selection}
              actions={actions}
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
      </>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
      <div className="flex flex-none flex-wrap items-center gap-2">
        <FilterHistoryControls
          canGoBack={queryControls.canGoBack}
          canGoForward={queryControls.canGoForward}
          onBack={queryControls.back}
          onForward={queryControls.forward}
        />
        <Button
          size="sm"
          onClick={() => setSettingsOpen(true)}>
          Order and filter
        </Button>
        <Button
          size="sm"
          disabledReason={queryControls.clearAllRefusal ?? undefined}
          onClick={queryControls.clearAll}>
          Remove all filters
        </Button>
        <Button
          size="sm"
          disabledReason={filterByCellRefusal ?? undefined}
          onClick={filterByCell}>
          Filter by this value
        </Button>
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
            ? shownExecutionId
              ? 'Loading rows…'
              : 'Running…'
            : selection.selectedCount > 0
              ? `${selection.selectedCount} ${selection.selectedCount === 1 ? 'cell' : 'cells'} selected on this page`
              : ''}
        </p>
      </div>

      <ExpressionBar
        expression={query.expression}
        onApply={(expression) => apply({expression})}
      />

      {/* One banner at a time, and the exploration's own failure outranks the results
          read: a statement that failed is WHY its rows could not be fetched, and saying
          both names the symptom twice. */}
      {error != null ? (
        <ErrorBanner error={error} />
      ) : (
        shownExecutionId !== null && results.isError && <ErrorBanner error={results.error} />
      )}

      {body()}

      <ColumnsPanel
        open={columnsOpen}
        onClose={() => setColumnsOpen(false)}
        geometry={geometry}
      />

      {settingsOpen && (
        <OrderFilterDialog
          columns={geometry.all}
          query={query}
          onCancel={() => setSettingsOpen(false)}
          onApply={({query: staged, hiddenColumns, pinnedColumns}) => {
            setSettingsOpen(false);
            // Two writes in one handler, so React batches them into one render and one
            // rendered statement — however many criteria changed, the dialog is one
            // execution (AC2). The presentation half renders no SQL and so adds none (AC4).
            onPresentationChange((p) => ({...p, hiddenColumns, pinnedColumns}));
            apply(staged);
          }}
        />
      )}
    </div>
  );
}
