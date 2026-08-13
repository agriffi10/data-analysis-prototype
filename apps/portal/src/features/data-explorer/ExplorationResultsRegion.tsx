import {useMemo, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {ErrorBanner} from '../../components/ErrorBanner';
import {Pager} from '../../components/Pager';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useQueryResults} from '../catalog/useQueryResults';
import {CALC_DEFAULT_FUNCTIONS, EXPLORATION_PAGE_SIZE} from './dataExplorer.constants';
import {CalcPanel} from './CalcPanel';
import {percentageColumnName, percentageOfTotal, selectedCellValues} from './calc';
import {ColumnsPanel} from './ColumnsPanel';
import {GeneratedSqlDisclosure} from './GeneratedSqlDisclosure';
import {GroupingPanel} from './GroupingPanel';
import {ExplorationGrid} from './ExplorationGrid';
import {ExplorationRecordView} from './ExplorationRecordView';
import {ExplorationTextView} from './ExplorationTextView';
import {ExpressionBar} from './ExpressionBar';
import {FilterValueDialog} from './FilterValueDialog';
import {FilterHistoryControls} from './FilterHistoryControls';
import {OrderFilterDialog} from './OrderFilterDialog';
import {PresentationSwitch} from './PresentationSwitch';
import {ValuePanel} from './ValuePanel';
import {useCellSelection} from './useCellSelection';
import {useColumnGeometry} from './useColumnGeometry';
import {aggregateAlias, isBareNumeric} from './renderExplorationSql';
import {
  clearFilter,
  clearSort,
  filterOf,
  filterValueKind,
  operatorTakesValue,
  setFilter,
  setGrouping,
  setSort,
  sortOf
} from './explorationQueryOps';
import type {ColumnQueryActions} from './ColumnFilterMenu';
import type {QueryColumn} from '../catalog/catalog.types';
import type {CalcPanelState, ExplorationPresentation, FilterOperator, GridPresentation} from './dataExplorer.types';
import type {UseExplorationQueryResult} from './useExplorationQuery';

export type ExplorationResultsRegionProps = {
  /** The tab these rows belong to — what the fallback execution below is scoped by. */
  tabId: string;
  /**
   * The statement that was run, straight from `useExploration` (SPEC-182 FR-005).
   *
   * Passed down rather than rendered here, so the disclosure shows the string the
   * execution used and the two cannot drift.
   */
  sql: string | null;
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
  tabId,
  sql,
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
  const [calcOpen, setCalcOpen] = useState(false);
  const [groupingOpen, setGroupingOpen] = useState(false);
  // What a header drag is carrying, so the Grouping panel can be a drop target for it. A
  // ref rather than state: the drop handler reads it at event time and nothing renders
  // from it, so a drag would otherwise re-render the whole grid on every start and end.
  const draggedColumn = useRef<string | null>(null);
  // Which aggregates the Calc panel shows: a preference of this SURFACE, not of the tab,
  // so it is held here rather than in the exploration's presentation — it describes a
  // selection, and a selection does not survive a page change, let alone a session.
  const [calc, setCalc] = useState<CalcPanelState>({functions: CALC_DEFAULT_FUNCTIONS, includeStrings: false});
  const [pendingFilter, setPendingFilter] = useState<{column: string; operator: FilterOperator} | null>(null);
  const gridRef = useRef<HTMLTableElement>(null);
  const {query, apply} = queryControls;

  // The last execution whose rows actually arrived. A failed apply falls back to it, so
  // the grid keeps showing something true rather than going blank behind a banner.
  //
  // Scoped to the TAB, and this component is not remounted per tab: without the reset, a
  // failed apply in one tab drew the OTHER tab's rows and columns under its own error
  // banner (found in review).
  const [lastGood, setLastGood] = useState<{tabId: string; executionId: string} | null>(null);
  const lastGoodExecutionId = lastGood?.tabId === tabId ? lastGood.executionId : null;
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
    setLastGood({tabId, executionId: queryExecutionId});
  }

  // SPEC-180 FR-006: a `table` source knows its columns from Glue before anything runs, a
  // `sql` source only from the execution. The execution's own metadata WINS once it lands
  // — grouping changes the column set entirely, and Glue would still be describing the
  // table underneath it.
  const executionColumns = results.columns.length > 0 ? results.columns : schemaColumns;

  // SPEC-182 FR-004 AC2: the percentage is computed HERE, from rows already fetched, and
  // appended as a real column so it sizes, hides and pins like any other. It is deliberately
  // not in the SQL — a windowed total would be a second scan of the same data for a column
  // the user asked to SEE.
  const percentage = useMemo(() => {
    const grouping = query.grouping;
    if (!grouping?.showPercentage || grouping.aggregates.length === 0) return null;
    const alias = aggregateAlias(grouping.aggregates[0]);
    // Located in the EXECUTION's columns rather than assumed to be last: an aggregate the
    // running statement does not have is a grouping the user has since changed, and a
    // percentage of the wrong column is worse than none.
    const index = results.columns.findIndex((column) => column.name === alias);
    if (index === -1) return null;
    return {
      column: {name: percentageColumnName(alias), type: 'varchar'},
      cells: percentageOfTotal(results.rows.map((row) => row[index] ?? null))
    };
  }, [query.grouping, results.columns, results.rows]);

  const columns = useMemo(
    () => (percentage ? [...executionColumns, percentage.column] : executionColumns),
    [executionColumns, percentage]
  );
  // The appended value sits at the appended column's index, which is what
  // `useColumnGeometry` assigns it — every row Athena returns is exactly as long as its
  // column list, so the two agree by construction.
  const rows = useMemo(
    () => (percentage ? results.rows.map((row, index) => [...row, percentage.cells[index]]) : results.rows),
    [percentage, results.rows]
  );

  const geometry = useColumnGeometry(columns, presentation, onPresentationChange);
  const visibleNames = geometry.visible.map((column) => column.name);
  // Paging clears the selection rather than carrying coordinates onto different rows
  // (FR-002 AC8), and so does a change to the column set — a row/column pair means
  // nothing once either axis has moved underneath it.
  const selection = useCellSelection(
    rows.length,
    visibleNames,
    `${shownExecutionId ?? ''}:${results.pageIndex}:${visibleNames.join(' ')}`,
    gridRef
  );

  // The cells Calc aggregates. Computed here rather than in the panel because the panel is
  // not always mounted and this is the only place holding all three inputs — and memoised
  // because it is recomputed on every cursor move.
  const selectedValues = useMemo(
    () => selectedCellValues(selection.selection.ranges, geometry.visible, rows),
    [selection.selection.ranges, geometry.visible, rows]
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

  // The value already on that column, so re-filtering it is an edit rather than a retype.
  const pendingExisting = pendingFilter ? filterOf(query, pendingFilter.column) : null;
  const pendingInitialValue =
    pendingExisting && operatorTakesValue(pendingExisting.operator) ? (pendingExisting.value ?? '') : '';

  // FR-007: below `tablet` an UNCHOSEN tab opens in Record — a horizontally-scrolling grid
  // on a 400px screen is not a data explorer. `useIsMobile` decides which view MOUNTS,
  // never how anything is styled (SPEC-095 FR-008), and a tab whose user HAS chosen keeps
  // that choice at every width, which is what `presentation: null` exists to express.
  const isMobile = useIsMobile();
  const view: GridPresentation = presentation.presentation ?? (isMobile ? 'record' : 'grid');

  // The stored row outlives the page it was taken on (a tab switch, a restore), so it is
  // clamped where it is READ.
  const recordRow = Math.min(Math.max(presentation.recordRowIndex, 0), Math.max(rows.length - 1, 0));

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
  const cursorValue = cursorColumn ? rows[cursorRow]?.[cursorColumn.index] : undefined;

  // Suspended is not loading: nothing is in flight, deliberately. Without this the status
  // line announced "Running…" directly above the panel saying nothing had been run.
  const loading = !queryControls.suspended && (isPending || !shownExecutionId || results.isPending);
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
    if (!loading && rows.length === 0) return <p className="p-4 text-sm text-text-2">No rows returned.</p>;

    return (
      <>
        <div className="flex min-h-0 flex-1 flex-col gap-2 tablet:flex-row">
          {view === 'grid' && (
            <ExplorationGrid
              columns={geometry.visible}
              rows={rows}
              rangeStart={results.rangeStart}
              geometry={geometry}
              selection={selection}
              actions={actions}
              onRequestFilterValue={(column, operator) => setPendingFilter({column, operator})}
              onColumnDrag={(name) => {
                draggedColumn.current = name;
              }}
              gridRef={gridRef}
            />
          )}
          {view === 'record' && (
            <ExplorationRecordView
              columns={geometry.visible}
              rows={rows}
              rowIndex={recordRow}
              rangeStart={results.rangeStart}
              onRowIndexChange={(next) => onPresentationChange((p) => ({...p, recordRowIndex: next}))}
              onFocusColumn={(column) => selection.selectCell({row: recordRow, column}, {})}
            />
          )}
          {view === 'text' && (
            <ExplorationTextView
              columns={geometry.visible}
              rows={rows}
              rangeStart={results.rangeStart}
              rangeEnd={results.rangeEnd}
            />
          )}

          {groupingOpen && (
            <GroupingPanel
              // The SOURCE's columns while grouping is in force, because the result's are
              // the grouping columns and the aggregate aliases by then — offering those
              // would let a user group by `count_all`.
              columns={query.grouping ? schemaColumns : geometry.all}
              query={query}
              draggedColumnRef={draggedColumn}
              onApply={(grouping) => apply(setGrouping(query, grouping))}
              onClose={() => setGroupingOpen(false)}
            />
          )}

          {calcOpen && (
            <CalcPanel
              values={selectedValues}
              state={calc}
              onStateChange={setCalc}
              onClose={() => setCalcOpen(false)}
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
          {queryControls.clearAllLabel}
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
        {/* Calc runs no query — opening it, changing its functions and re-selecting cells
            are all free, which is exactly why it aggregates the SELECTION and not the
            result set (FR-001 AC7). */}
        <Button
          size="sm"
          aria-pressed={calcOpen}
          onClick={() => setCalcOpen((open) => !open)}>
          Calc
        </Button>
        {/* Grouping is the sibling that is not one: opening the panel is free, but what it
            applies is a GROUP BY, and that is an execution like any other. */}
        <Button
          size="sm"
          aria-pressed={groupingOpen}
          onClick={() => setGroupingOpen((open) => !open)}>
          Grouping
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

      {/* Available whether or not grouping is active (FR-005 AC4): the Explorer writes SQL
          the user did not, grouped or otherwise, and every statement it writes is a bill. */}
      <GeneratedSqlDisclosure sql={sql} />

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

      {pendingFilter && (
        <FilterValueDialog
          column={pendingFilter.column}
          operator={pendingFilter.operator}
          valueKind={valueKindOf(pendingFilter.column)}
          initialValue={pendingInitialValue}
          onApply={(value) => {
            actions.filter(pendingFilter.column, pendingFilter.operator, value);
            setPendingFilter(null);
          }}
          onCancel={() => setPendingFilter(null)}
        />
      )}

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
