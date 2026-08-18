import {useMemo, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {ErrorBanner} from '../../components/ErrorBanner';
import {Pager} from '../../components/Pager';
import {useToast} from '../../components/toastContext';
import {useCopyToClipboard} from '../../lib/useCopyToClipboard';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useFeature} from '../feature-flags';
import {useQueryResults} from '../catalog/useQueryResults';
import {CALC_DEFAULT_FUNCTIONS, EXPLORATION_PAGE_SIZE, PLAIN_COPY_OPTIONS} from './dataExplorer.constants';
import {AdvancedCopyDialog} from './AdvancedCopyDialog';
import {renderCopy} from './renderCopy';
import {CalcPanel} from './CalcPanel';
import {percentageColumnName, percentageOfTotal, selectedCellValues} from './calc';
import {ColumnsPanel} from './ColumnsPanel';
import {RowColoursDialog} from './RowColoursDialog';
import {TransformersDialog} from './TransformersDialog';
import {computePageFormatting} from './formatting';
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
import type {QueryColumn, QueryState} from '../catalog/catalog.types';
import type {
  CalcPanelState,
  CopyOptions,
  ExplorationPresentation,
  FilterOperator,
  FormattingState,
  GridPresentation
} from './dataExplorer.types';
import type {UseExplorationQueryResult} from './useExplorationQuery';

export type ExplorationResultsRegionProps = {
  /** The tab these rows belong to — what the fallback execution below is scoped by. */
  tabId: string;
  /**
   * The statement that was run, straight from `useExploration`.
   *
   * Passed down rather than rendered here, so the disclosure shows the string the
   * execution used and the two cannot drift.
   */
  sql: string | null;
  queryExecutionId: string | null;
  /**
   * The execution's state, or null before the first poll lands.
   *
   * Load-bearing, not informational: results are read ONLY at `SUCCEEDED`. See the gate
   * on `shownExecutionId` — `isPending` cannot stand in for this.
   */
  state: QueryState | null;
  /** The exploration is starting or still running. */
  isPending: boolean;
  /** A render refusal, a failed start, a failed poll or a failed execution. */
  error: unknown;
  /**
   * Columns the SOURCE is known to have before any execution returns — Glue's, for a
   * `table` source. Empty for a `sql` source, whose columns are unknowable until the
   * first execution reports them.
   */
  schemaColumns: QueryColumn[];
  /** The active tab's presentation state — the grid's geometry lives here. */
  presentation: ExplorationPresentation;
  onPresentationChange: (update: (presentation: ExplorationPresentation) => ExplorationPresentation) => void;
  /** The query description and every operation over it. */
  queryControls: UseExplorationQueryResult;
  /** Raises the save dialog. The host owns the write; this owns the gesture. */
  onSaveQuery: () => void;
  /** Raises the export dialog. The host owns the copy; this owns the gesture. */
  onExport: () => void;
  /**
   * Why export is unavailable, or null when it is.
   *
   * Decided by the HOST, because export copies the execution's own results object and only
   * the host knows whether that object exists yet — this surface knows the rows, not where
   * Athena put them.
   */
  exportRefusal: string | null;
};

export const NO_CELL_TO_FILTER = 'Select a cell first.';
/**
 * Why the percentage column takes no filter and no sort.
 *
 * It is computed in the browser and appended to the result, so there is no such column in
 * the SQL: an `ORDER BY` on it is a description `renderExplorationSql` REFUSES — which
 * would take the whole exploration to an error banner — and a `WHERE` on it fails at
 * Athena as an unknown column. The refusal is user text; the renderer's own names a column
 * and an operator, which the error-wording rule forbids showing anyone.
 */
export const CALCULATED_COLUMN_REFUSAL =
  'This column is worked out in your browser, so it can’t be sorted or filtered.';
export const UNFILTERABLE_VALUE = 'This cell’s value can’t be used as a filter on a numeric column.';
export const SUSPENDED_TEXT = 'This set of filters failed last time it ran. Nothing has been run.';
/** No statement exists yet: nothing rendered, or a suspended description was held back. */
export const NOTHING_TO_SAVE = 'There’s no query to save yet — nothing has run.';
/**
 * Why a FAILED exploration cannot be saved.
 *
 * Its own wording because its own state: there IS a statement here, and it is the one
 * Athena rejected. The rows under the banner are the LAST GOOD execution's, so saving would
 * write one query while the grid showed another's rows — and the file would fail to open in
 * the Query workspace, which is the surface a saved exploration promises it opens in.
 */
export const FAILED_NOT_SAVEABLE = 'This query didn’t run, so there’s nothing to save. Fix it and try again.';
/** Copy takes a SELECTION, and an empty one has no rectangle to take. */
export const NOTHING_SELECTED_TO_COPY = 'Select some cells first.';
/**
 * A clipboard write the browser refused.
 *
 * Reachable rather than theoretical: Safari denies `writeText` outside a user gesture it
 * recognises, and an insecure context has no Clipboard API at all. The grid suppresses the
 * browser's own copy to make room for this one, so a silent failure leaves the previous
 * clipboard contents in place under the impression they are the new ones.
 */
export const COPY_FAILED = 'Your browser wouldn’t let the app write to the clipboard.';
/**
 * Why export is unavailable.
 *
 * Export copies the object Athena wrote, which exists only once an execution has SUCCEEDED
 * — so this covers a first run still in flight, a failed one, and a suspended description
 * alike. Copy is offered throughout, because the rows on screen are real either way.
 */
export const NOTHING_TO_EXPORT = 'Run a query first — export saves the results Athena returned.';

/**
 * One exploration's rows, and everything that changes which rows they are.
 *
 * The **query toolbar and the expression bar render whatever the results are doing** —
 * loading, empty, or failed. That is not cosmetic: a failed apply has to leave the user
 * somewhere they can correct it, and a toolbar that disappears with the
 * rows takes the correction with it.
 *
 * For the same reason a failure keeps the LAST GOOD execution's rows on screen beneath the
 * banner rather than emptying the grid. `useQueryResults` is pointed at that execution
 * while the current one is failed; paging it costs nothing, as paging never does.
 *
 * Errors go through `ErrorBanner`: Athena's own text never reaches a user, and
 * neither does an `ExplorationRenderError`, whose message names a column for an operator.
 */
export function ExplorationResultsRegion({
  tabId,
  sql,
  queryExecutionId,
  state,
  isPending,
  error,
  schemaColumns,
  presentation,
  onPresentationChange,
  queryControls,
  onSaveQuery,
  onExport,
  exportRefusal
}: ExplorationResultsRegionProps) {
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [calcOpen, setCalcOpen] = useState(false);
  const [groupingOpen, setGroupingOpen] = useState(false);
  const [coloursOpen, setColoursOpen] = useState(false);
  const [transformersOpen, setTransformersOpen] = useState(false);
  // What a header drag is carrying, so the Grouping panel can be a drop target for it. A
  // ref rather than state: the drop handler reads it at event time and nothing renders
  // from it, so a drag would otherwise re-render the whole grid on every start and end.
  const draggedColumn = useRef<string | null>(null);
  // Which aggregates the Calc panel shows: a preference of this SURFACE, not of the tab,
  // so it is held here rather than in the exploration's presentation — it describes a
  // selection, and a selection does not survive a page change, let alone a session.
  //
  // It opens on MIXED aggregation, and that default is not arbitrary: numbers-only narrows
  // every function, so a numbers-only default answers `Count 0` over a selection of three
  // text cells while the line above it reads "3 selected cells" — the one pair of numbers
  // this panel must never show together. The functions are COPIED out of the constant,
  // which is state from here on.
  const [calc, setCalc] = useState<CalcPanelState>({functions: [...CALC_DEFAULT_FUNCTIONS], includeStrings: true});
  const [pendingFilter, setPendingFilter] = useState<{column: string; operator: FilterOperator} | null>(null);
  const gridRef = useRef<HTMLTableElement>(null);
  const {query, apply} = queryControls;
  const savedQueriesEnabled = useFeature('query');
  const toast = useToast();
  const {copy} = useCopyToClipboard();

  // The last execution whose rows actually arrived. A failed apply falls back to it, so
  // the grid keeps showing something true rather than going blank behind a banner.
  //
  // Scoped to the TAB, and this component is not remounted per tab: without the reset, a
  // failed apply in one tab drew the OTHER tab's rows and columns under its own error
  // banner (found in review).
  const [lastGood, setLastGood] = useState<{tabId: string; executionId: string} | null>(null);
  const lastGoodExecutionId = lastGood?.tabId === tabId ? lastGood.executionId : null;
  const failed = Boolean(error);
  // Results are read ONLY once the execution has SUCCEEDED. `useQueryResults` documents
  // itself as a pager "over a succeeded query's results" and cannot enforce that — it is
  // handed an id and never sees the execution's state — so the contract is kept here.
  //
  // Without the gate, `GetQueryResults` fires the moment `StartQueryExecution` returns an
  // id, against a QUEUED execution, and Athena answers **400 INVALID_QUERY_EXECUTION_STATE
  // — "Query has not yet finished"**. That error's name (`InvalidRequestException`) maps to
  // nothing, so it fell through to the generic fallback and an ordinary first load showed
  // the user "Something went wrong. Contact the Administrator." It read as intermittent
  // only because TanStack's `retry: 1` usually landed after the query had finished.
  //
  // `isPending` is NOT a substitute, and that is the trap: between `StartQueryExecution`
  // resolving and the FIRST poll landing, `state` is still null, so `isPending`'s
  // `state !== null && !isTerminalState(state)` clause is already false. That window is
  // precisely where the race lived.
  const shownExecutionId = failed ? lastGoodExecutionId : state === 'SUCCEEDED' ? queryExecutionId : null;

  const results = useQueryResults(shownExecutionId, EXPLORATION_PAGE_SIZE);
  // Recorded during render (React's "adjust state when a prop changes" pattern, as
  // `useCellSelection` and `useQueryResults` do) rather than in an effect: an effect would
  // paint one frame in which a failure had emptied the grid before the fallback arrived.
  //
  // Judged on `shownExecutionId`, the id these results actually belong to — NOT on
  // `queryExecutionId`. The two differ for the whole QUEUED window, and reading the ungated
  // one here would be correct only by an unstated TanStack property (that a DISABLED
  // `useInfiniteQuery` reports `isPending`). If that ever stopped holding, a still-running
  // execution would be recorded as "last good", and when it then FAILED the fallback would
  // point at an execution that never produced rows — a banner over a blank grid, which is
  // the exact state this fallback exists to prevent.
  if (
    !failed &&
    shownExecutionId !== null &&
    !results.isPending &&
    !results.isError &&
    lastGoodExecutionId !== shownExecutionId
  ) {
    setLastGood({tabId, executionId: shownExecutionId});
  }

  // a `table` source knows its columns from Glue before anything runs, a
  // `sql` source only from the execution. The execution's own metadata WINS once it lands
  // — grouping changes the column set entirely, and Glue would still be describing the
  // table underneath it.
  const executionColumns = results.columns.length > 0 ? results.columns : schemaColumns;

  // The percentage is computed HERE, from rows already fetched, and
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

  // Resolved from the rows already on screen, which is the whole spec: every
  // gesture behind this is a state write, so the grid repaints and NOTHING is fetched. It is
  // memoised because it is recomputed on every render of a region that re-renders on every
  // cursor move.
  // Evaluated over `geometry.all`, HIDDEN COLUMNS INCLUDED, and that is deliberate: a
  // hidden column is still part of the row, so a rule reading `status` must keep painting
  // the row after `status` is hidden — and the two dialogs are handed `all` too, so what
  // they call applicable is what the evaluator can actually see. Judged over `visible`,
  // the dialog reported a rule as fine while it silently did nothing (found in review).
  // Formats for hidden columns are simply never looked up.
  const pageFormatting = useMemo(
    () => computePageFormatting(presentation.formatting, geometry.all, rows),
    [presentation.formatting, geometry.all, rows]
  );

  const setFormatting = (update: Partial<FormattingState>) =>
    onPresentationChange((p) => ({...p, formatting: {...p.formatting, ...update}}));

  const typeOf = useMemo(() => new Map(geometry.all.map((column) => [column.name, column.type])), [geometry.all]);
  const valueKindOf = (column: string) => filterValueKind(typeOf.get(column) ?? '');

  // Every per-column gesture goes through ONE object, and every one of them is a single
  // `apply` — so a menu choice is a description change, and a description change is at
  // most one execution.
  const actions: ColumnQueryActions = {
    // The ONE reader every filter and sort surface asks first. Today it names exactly the
    // appended percentage column, which the grid draws like any other and the SQL has
    // never heard of.
    queryRefusalOf: (column) => (column === percentage?.column.name ? CALCULATED_COLUMN_REFUSAL : null),
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

  // Below `tablet` an UNCHOSEN tab opens in Record — a horizontally-scrolling grid
  // on a 400px screen is not a data explorer. `useIsMobile` decides which view MOUNTS,
  // never how anything is styled, and a tab whose user HAS chosen keeps
  // that choice at every width, which is what `presentation: null` exists to express.
  const isMobile = useIsMobile();
  const view: GridPresentation = presentation.presentation ?? (isMobile ? 'record' : 'grid');

  // The stored row outlives the page it was taken on (a tab switch, a restore), so it is
  // clamped where it is READ.
  const recordRow = Math.min(Math.max(presentation.recordRowIndex, 0), Math.max(rows.length - 1, 0));

  // Record and the grid share ONE focused row, and the sync runs in BOTH directions —
  // entering Record from the cursor, and moving the cursor to the row Record left off at
  // Only the first half shipped at first, so "switch back" landed on
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
  // THE RAW CELL VALUE, never `cellText` and never a formatted rendering: a
  // NULL reads as "NULL" on screen and a transformed URL will not look like its value at
  // all, and either one as a predicate matches nothing.
  const cursorValue = cursorColumn ? rows[cursorRow]?.[cursorColumn.index] : undefined;

  // Suspended is not loading: nothing is in flight, deliberately. Without this the status
  // line announced "Running…" directly above the panel saying nothing had been run.
  const loading = !queryControls.suspended && (isPending || !shownExecutionId || results.isPending);

  // `failed` is checked FIRST and is the one that is easy to miss: a failed
  // apply still has a rendered `sql` — the statement Athena rejected — while `shownExecutionId`
  // has fallen back to the last good one, so the grid is showing a DIFFERENT query's rows. A
  // save there writes a file that fails to open in the workspace it promises it opens in.
  // A suspended description needs no clause of its own: the workspace passes `useExploration`
  // nothing while suspended, so `sql` is already null.
  const saveRefusal = failed ? FAILED_NOT_SAVEABLE : sql === null ? NOTHING_TO_SAVE : null;
  const hasCell = cursorColumn !== null && cursorValue !== undefined;
  const filterByCellRefusal = !hasCell
    ? NO_CELL_TO_FILTER
    : // The cursor can sit in the calculated column like any other, and this action does
      // not go through the header menu — so it asks the same reader the menu does.
      (actions.queryRefusalOf(cursorColumn.name) ??
      (cursorValue !== null &&
      valueKindOf(cursorColumn.name) === 'number' &&
      !isBareNumeric(cursorValue) /* a numeric column's value is emitted BARE, so one
        the renderer would refuse has to be refused at the gesture instead — the refusal
        it throws is operator text. */
        ? UNFILTERABLE_VALUE
        : null));

  // THE ROWS, not the rendering. `renderCopy` is handed `rows` — the raw page, transformed
  // values and all left behind — because a URL column pasted into a spreadsheet has to carry
  // its value, not its link text. Every argument here is already in memory, so
  // a copy issues nothing however often it is used.
  const copySelection = async (options: CopyOptions): Promise<boolean> => {
    const text = renderCopy(selection.selection, geometry.visible, rows, options, results.rangeStart);
    // Nothing selected, or every range names a column this result no longer has. Not a
    // failure and not a success — there was nothing to put on the clipboard.
    if (text === '') return false;
    return copy(text);
  };

  /**
   * The plain Ctrl/Cmd+C. Silent on success — the paste IS the confirmation — but never
   * silent on failure, because the browser's own copy was suppressed to make room for this
   * one and the user would otherwise paste whatever was on the clipboard before.
   */
  const plainCopy = () => {
    void copySelection(PLAIN_COPY_OPTIONS).then((copied) => {
      if (!copied && selection.selectedCount > 0) toast.push({variant: 'danger', message: COPY_FAILED});
    });
  };

  const advancedCopy = (options: CopyOptions) => {
    setCopyOpen(false);
    // AWAITED, and the message follows the outcome. `useCopyToClipboard` swallows a refused
    // write — which is safe for a caller that renders its `copied` flag and a lie for this
    // one, which has just closed the dialog and has to say what happened. A denied clipboard
    // permission would otherwise be reported as a successful copy, and the user would paste
    // whatever was there before.
    void copySelection(options).then((copied) =>
      toast.push(
        copied ? {variant: 'success', message: 'Copied to the clipboard.'} : {variant: 'danger', message: COPY_FAILED}
      )
    );
  };

  const filterByCell = () => {
    if (!cursorColumn || cursorValue === undefined) return;
    // A NULL cell is `IS NULL`, not `= ''`. Athena hands every value back as
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
    // say what its columns are. That is the `sql` arm's ordinary state — and
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
              formatting={pageFormatting}
              onRequestFilterValue={(column, operator) => setPendingFilter({column, operator})}
              onColumnDrag={(name) => {
                draggedColumn.current = name;
              }}
              onCopy={plainCopy}
              gridRef={gridRef}
            />
          )}
          {view === 'record' && (
            <ExplorationRecordView
              columns={geometry.visible}
              rows={rows}
              rowIndex={recordRow}
              rangeStart={results.rangeStart}
              formats={pageFormatting.formats}
              transformed={pageFormatting.transformed}
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
              type={cursorColumn?.type ?? null}
              transformed={cursorColumn ? pageFormatting.transformed[cursorRow]?.[cursorColumn.name] : null}
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
        {/* Colours, striping and the type tint change how the rows on screen LOOK and
            nothing about which rows they are — so unlike Grouping beside it, opening this
            and applying what it stages are both free. */}
        <Button
          size="sm"
          onClick={() => setColoursOpen(true)}>
          Colours
        </Button>
        <Button
          size="sm"
          onClick={() => setTransformersOpen(true)}>
          Transformers
        </Button>
        <Button
          size="sm"
          aria-pressed={presentation.valuePanelOpen}
          onClick={() => onPresentationChange((p) => ({...p, valuePanelOpen: !p.valuePanelOpen}))}>
          Value
        </Button>
        {/* Calc runs no query — opening it, changing its functions and re-selecting cells
            are all free, which is exactly why it aggregates the SELECTION and not the
            result set. */}
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
        {/* Copy issues nothing and never has — see `renderCopy`. The plain Ctrl/Cmd+C is on
            the grid; this is the same copy with the formats and toggles a destination other
            than a spreadsheet wants. */}
        <Button
          size="sm"
          disabledReason={selection.selectedCount === 0 ? NOTHING_SELECTED_TO_COPY : undefined}
          onClick={() => setCopyOpen(true)}>
          Copy…
        </Button>
        {/* Export writes the EXECUTION's own results object, so a filtered, ordered or
            grouped exploration exports exactly what is on screen without a second query and
            without a second bill. The refusal comes from the host, which is
            what knows whether that object exists yet. */}
        <Button
          size="sm"
          disabledReason={exportRefusal ?? undefined}
          onClick={onExport}>
          Export
        </Button>
        {/* Gated by `query`, not `dataExplorer`: the store is the Query workspace's, and
            REMOVED rather than refused, because a reason cannot explain a state the user has
            no way to change. See `gatedSurfaces.ts`. */}
        {savedQueriesEnabled && (
          <Button
            size="sm"
            disabledReason={saveRefusal ?? undefined}
            onClick={onSaveQuery}>
            Save as query
          </Button>
        )}
        {/* The count says "on this page" every time it is said, because that is the only
            thing a selection here can ever mean — Ctrl/Cmd+A included. */}
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

      {/* Available whether or not grouping is active: the Explorer writes SQL
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

      {copyOpen && (
        <AdvancedCopyDialog
          selectedCount={selection.selectedCount}
          onCopy={advancedCopy}
          onCancel={() => setCopyOpen(false)}
        />
      )}

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

      {coloursOpen && (
        <RowColoursDialog
          columns={geometry.all.map((column) => column.name)}
          formatting={presentation.formatting}
          onCancel={() => setColoursOpen(false)}
          onApply={(settings) => {
            setColoursOpen(false);
            setFormatting(settings);
          }}
        />
      )}

      {transformersOpen && (
        <TransformersDialog
          columns={geometry.all.map((column) => column.name)}
          transformers={presentation.formatting.transformers}
          onCancel={() => setTransformersOpen(false)}
          onApply={(transformers) => {
            setTransformersOpen(false);
            setFormatting({transformers});
          }}
        />
      )}

      {settingsOpen && (
        <OrderFilterDialog
          columns={geometry.all}
          queryRefusalOf={actions.queryRefusalOf}
          query={query}
          onCancel={() => setSettingsOpen(false)}
          onApply={({query: staged, hiddenColumns, pinnedColumns}) => {
            setSettingsOpen(false);
            // Two writes in one handler, so React batches them into one render and one
            // rendered statement — however many criteria changed, the dialog is one
            // execution. The presentation half renders no SQL and so adds none.
            onPresentationChange((p) => ({...p, hiddenColumns, pinnedColumns}));
            apply(staged);
          }}
        />
      )}
    </div>
  );
}
