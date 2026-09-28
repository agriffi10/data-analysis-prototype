import {useEffect, useEffectEvent, useMemo, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {Chip, ChipList} from '../../components/Chip';
import {ErrorBanner} from '../../components/ErrorBanner';
import {Pager} from '../../components/Pager';
import {useToast} from '../../components/toastContext';
import {useCopyToClipboard} from '../../lib/useCopyToClipboard';
import {useFeature} from '../feature-flags';
import {useQueryResults} from '../catalog/useQueryResults';
import {useResultRowCount} from '../catalog/useResultRowCount';
import {formatCount} from '../../lib/format';
import {isQueryStillRunning} from '../catalog/useQueryExecution';
import {CALC_DEFAULT_FUNCTIONS, EXPLORATION_PAGE_SIZE, PLAIN_COPY_OPTIONS} from './dataExplorer.constants';
import {AdvancedCopyDialog} from './AdvancedCopyDialog';
import {renderCopy} from './renderCopy';
import {CalcPanel} from './CalcPanel';
import {percentageColumnName, percentageOfTotal, selectedCellValues} from './calc';
import {ColumnsPanel} from './ColumnsPanel';
import {RowColoursDialog} from './RowColoursDialog';
import {TransformersDialog} from './TransformersDialog';
import {useTheme} from '../../lib/useTheme';
import {computePageFormatting} from './formatting';
import {GeneratedSqlDisclosure} from './GeneratedSqlDisclosure';
import {GroupingPanel} from './GroupingPanel';
import {ExplorationGrid} from './ExplorationGrid';
import {ExpressionBar} from './ExpressionBar';
import {FilterValueDialog} from './FilterValueDialog';
import {FilterHistoryControls} from './FilterHistoryControls';
import {ExplorationOptionsMenu} from './ExplorationOptionsMenu';
import {OrderFilterDialog} from './OrderFilterDialog';
import {ValuePanel} from './ValuePanel';
import {useCellSelection} from './useCellSelection';
import {exportColumnIndexes} from './exportColumns';
import {useColumnGeometry} from './useColumnGeometry';
import {aggregateAlias} from './renderExplorationSql';
import {FilterByValueDialog, type FilterByValueResult} from './FilterByValueDialog';
import {
  clearFilter,
  clearSort,
  filterItemLabel,
  filterOf,
  filterValueKind,
  operatorTakesValue,
  operatorsFor,
  removeFilterItem,
  setFilter,
  setGrouping,
  setSort,
  sortOf
} from './explorationQueryOps';
import type {ColumnQueryActions} from './ColumnFilterMenu';
import type {QueryColumn, QueryState} from '../catalog/catalog.types';
import {heldText, leftOutNote} from './savedView';
import type {
  AwaitingRun,
  CalcPanelState,
  CopyOptions,
  ExplorationPresentation,
  ExplorationSource,
  FilterItem,
  FilterOperator,
  FormattingState
} from './dataExplorer.types';
import type {UseExplorationQueryResult} from './useExplorationQuery';

export type ExplorationResultsRegionProps = {
  /** The tab these rows belong to — what the fallback execution below is scoped by. */
  tabId: string;
  /** Where the tab's rows come from, which the values picker lists from; null with no tab. */
  source: ExplorationSource | null;
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
  /**
   * Set while the tab is held: reopened from a shared space's saved view and not yet run. The
   * statement is rendered and on screen, and nothing has started.
   */
  held?: AwaitingRun | null;
  /** Runs a held tab's statement. */
  onRun?: () => void;
  /** Raises the save dialog. The host owns the write; this owns the gesture. */
  onSaveQuery: () => void;
  /**
   * Opens a copy of the generated statement in a new Query tab. The host owns the navigation and
   * the tab's label; this region offers the control only while the `query` flag is on.
   */
  onOpenInQuery?: (sql: string) => void;
  /** Turn the exploration in front of the user into a catalog view — `Save as query`'s
   *  sibling: one writes a `.sql` file, the other writes a view. */
  onCreateView: () => void;
  /**
   * A reason the HOST knows and this region does not — today, that the source is a statement
   * rather than a table, so there is no single database to create the view in. Combined with
   * this region's own reasons rather than replacing them, so a control that is refused for two
   * reasons still names the one the user can act on first.
   */
  createViewRefusal?: string | null;
  /**
   * Raises the save-results dialog, with the result columns the grid is showing.
   *
   * The list is this surface's to compute because only it knows what is hidden and in what
   * order; what to DO with it is the host's, which owns the save.
   */
  onExport: (columnIndexes: number[] | null) => void;
  /**
   * Why export is unavailable, or null when it is.
   *
   * Decided by the HOST, because export copies the execution's own results object and only
   * the host knows whether that object exists yet — this surface knows the rows, not where
   * Athena put them.
   */
  exportRefusal: string | null;
  /**
   * Reports the columns of an execution that ran with NO grouping — a `sql` source's own
   * columns, which the host remembers on the tab because nothing else knows them.
   *
   * Reported only for the CURRENT execution once it has succeeded: never for the last good
   * one a failure falls back to, whose description may have been grouped.
   */
  onSourceColumns?: (tabId: string, columns: QueryColumn[]) => void;
};

export const NO_CELL_TO_FILTER = 'Select a cell first.';

/** A filter chip's remove control, named for the whole label so a truncated chip is still read out. */
function chipRemoveLabel(item: FilterItem): string {
  return `Remove filter: ${filterItemLabel(item)}`;
}
/**
 * Why a save is refused when the grid shows no column the result has.
 *
 * `useColumnGeometry` refuses to hide the last VISIBLE column, so the grid always draws
 * something — but that something need not be a column of this result. A grouped exploration's
 * percentage column is computed in the browser and is in no result; and a stored hide is never
 * pruned, deliberately, so one that names every column of a re-executed result leaves the grid
 * drawing nothing but its row numbers. Both reach here, and neither is a state to refuse a save
 * from silently.
 */
export const NO_RESULT_COLUMN_TO_SAVE = 'Show at least one of the result’s columns to save it.';
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
/** Why a column's values cannot be listed: every tick becomes an `is one of`, which only these columns offer. */
export const FILTER_BY_VALUE_TYPES_REFUSAL = 'Filter by value works on text and number columns.';
/** Why a grouped view's aggregate cannot be listed: the listing reads the rows before grouping, which have no such column. */
export const AGGREGATE_FILTER_BY_VALUE_REFUSAL =
  'This column is worked out by the grouping, so its values can’t be listed.';
/**
 * Why a held tab's values cannot be listed. The listing carries the filter expression, and a held
 * tab's is SQL from a shared file the user has not yet chosen to run.
 */
export const HELD_FILTER_BY_VALUE_REFUSAL = 'Run the view first.';
export const SUSPENDED_TEXT = 'This version of the query failed last time it ran. Nothing has been run.';

/**
 * No statement exists: nothing rendered yet, the description was refused before it could, or a
 * suspended one was held back. Worded to be true in all three, so it names no cause.
 */
export const NOTHING_TO_SAVE = 'There’s no query to save yet.';
/**
 * Why a FAILED exploration cannot be saved.
 *
 * Its own wording because its own state: there IS a statement here, and it is the one
 * Athena rejected. The rows under the banner are the LAST GOOD execution's, so saving would
 * write one query while the grid showed another's rows — and the file would fail to open in
 * the Query workspace, which is the surface a saved exploration promises it opens in.
 */
export const FAILED_NOT_SAVEABLE = 'This query didn’t succeed, so there’s nothing to save yet.';
/** The two reasons above, for Create view, which makes a view rather than saving a file. */
export const NOTHING_TO_VIEW = 'There’s no query to make a view from yet.';
export const FAILED_NO_VIEW = 'This query didn’t succeed, so there’s nothing to make a view from yet.';
/** `Open in Query`'s refusal. A failed statement still opens: fixing it in Query is the point. */
export const NOTHING_TO_OPEN = 'There’s no statement to open yet.';
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
 * alike. Copy is offered throughout, because the rows on screen are real either way. It never
 * says there are no results, because a failed apply leaves the last good rows on screen.
 */
export const NOTHING_TO_EXPORT = 'There’s nothing to save until this query finishes successfully.';

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
 * Errors go through `ErrorBanner`: Athena's own text reaches a user only as the closed Details
 * of a failure in their own SQL, and an `ExplorationRenderError`, whose message names a column
 * for an operator, never does.
 */
export function ExplorationResultsRegion({
  tabId,
  source,
  sql,
  queryExecutionId,
  state,
  isPending,
  error,
  schemaColumns,
  presentation,
  onPresentationChange,
  queryControls,
  held = null,
  onRun,
  onSaveQuery,
  onOpenInQuery,
  onCreateView,
  createViewRefusal,
  onExport,
  exportRefusal,
  onSourceColumns
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
  // The values picker's column, and the cell it was opened on when the Options menu opened it.
  const [filterByValue, setFilterByValue] = useState<{column: string; seed: {value: string | null} | null} | null>(
    null
  );
  const gridRef = useRef<HTMLTableElement>(null);
  const {query, apply} = queryControls;
  // One flag, three consumers now: the saved-query store, the catalog view and Open in Query.
  // All three are Query capabilities wearing Data Explorer controls.
  const queryEnabled = useFeature('query');
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
  // The banner may be the verdict that the browser stopped watching a statement still running.
  // It falls back to the last good rows like a failure does, and is worded and coloured apart.
  const stillRunning = isQueryStillRunning(error);
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
  // The Query workspace's total, by the same rule: the pager's own count once it holds the last
  // page, else Athena's, and never a number below the rows already loaded — that is not a total.
  const rowCount = useResultRowCount(shownExecutionId);
  const pagerTotal = results.columns.length > 0 ? results.totalRowCount : null;
  const shownTotal =
    pagerTotal ?? (rowCount.total !== null && rowCount.total >= results.loadedRowCount ? rowCount.total : null);
  const totalLabel = shownTotal !== null ? ` of ${formatCount(shownTotal)}` : rowCount.isCounting ? ' · counting…' : '';
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

  const reportSourceColumns = useEffectEvent((forTab: string, sourceColumns: QueryColumn[]) =>
    onSourceColumns?.(forTab, sourceColumns)
  );
  const ungrouped = query.grouping === null;
  // `!failed` is what keeps the last-good fallback out: after a failed ungroup it shows the GROUPED
  // execution while the description already says ungrouped.
  const settledColumns = !failed && state === 'SUCCEEDED' && ungrouped && !results.isPending ? results.columns : null;
  useEffect(() => {
    if (settledColumns && settledColumns.length > 0) reportSourceColumns(tabId, settledColumns);
  }, [tabId, settledColumns]);

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
  // Resolved against the EXECUTION's own columns, never `executionColumns`, which falls back to
  // the Glue schema before a result lands — a position in that fallback is a position in a
  // different list, and the plane resolves nothing.
  const exportColumns = exportColumnIndexes(
    results.columns.map((column) => column.name),
    visibleNames
  );
  // An empty list is the one case a save cannot be made from. It is distinguished from `null`,
  // which is "every column, in order" and includes the window before a result has landed: a
  // refusal there would refuse a save that is about to be perfectly fine. The host's refusal
  // covers that window anyway; this must not be the thing relying on it.
  const noResultColumnShown = exportColumns !== null && exportColumns.length === 0;
  // The HOST's reason comes first: "nothing has finished running" is true of a grid that also
  // happens to show no result column, and it is the one the user can act on.
  const saveResultsRefusal = exportRefusal ?? (noResultColumnShown ? NO_RESULT_COLUMN_TO_SAVE : null);
  // Paging clears the selection rather than carrying coordinates onto different rows
  // and so does a change to the column set — a row/column pair means
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
  // The theme is a dependency because a GRADIENT mixes two tints into a literal colour —
  // every other colour here is a CSS variable that re-resolves on its own.
  const {effective} = useTheme();
  const pageFormatting = useMemo(
    () => computePageFormatting(presentation.formatting, geometry.all, rows, effective),
    [presentation.formatting, geometry.all, rows, effective]
  );

  const setFormatting = (update: Partial<FormattingState>) =>
    onPresentationChange((p) => ({...p, formatting: {...p.formatting, ...update}}));

  const typeOf = useMemo(() => new Map(geometry.all.map((column) => [column.name, column.type])), [geometry.all]);
  const valueKindOf = (column: string) => filterValueKind(typeOf.get(column) ?? '');

  // The ONE reader every filter and sort surface asks first. Today it names exactly the appended
  // percentage column, which the grid draws like any other and the SQL has never heard of.
  const queryRefusalOf = (column: string) => (column === percentage?.column.name ? CALCULATED_COLUMN_REFUSAL : null);

  // Every per-column gesture goes through ONE object, and every one of them is a single
  // `apply` — so a menu choice is a description change, and a description change is at
  // most one execution.
  const actions: ColumnQueryActions = {
    queryRefusalOf,
    sortOf: (column) => sortOf(query, column),
    sortCount: query.ordering.length,
    filterOf: (column) => filterOf(query, column),
    valueKindOf,
    sort: (column, direction) => apply({ordering: setSort(query, column, direction).ordering}),
    clearSort: (column) => apply({ordering: clearSort(query, column).ordering}),
    operatorsOf: (column) => operatorsFor(typeOf.get(column) ?? ''),
    filterByValueRefusalOf: (column) => {
      const refusal = queryRefusalOf(column);
      if (refusal !== null) return refusal;
      if (query.grouping?.aggregates.some((a) => aggregateAlias(a) === column))
        return AGGREGATE_FILTER_BY_VALUE_REFUSAL;
      return operatorsFor(typeOf.get(column) ?? '').includes('in') ? null : FILTER_BY_VALUE_TYPES_REFUSAL;
    },
    // `setFilter` drops whichever of the two fields this operator does not read, so a
    // caller cannot leave a stale value behind on the way to a list operator.
    filter: (column, operator, input) =>
      apply({
        filters: setFilter(query, {
          column,
          operator,
          value: input && 'value' in input ? input.value : operatorTakesValue(operator) ? '' : undefined,
          values: input && 'values' in input ? input.values : undefined,
          includesNull: input && 'values' in input ? input.includesNull : undefined,
          valueKind: valueKindOf(column)
        }).filters
      }),
    clearFilter: (column) => apply({filters: clearFilter(query, column).filters})
  };

  // Removing a chip unmounts the button focus was on, which would leave it on the page body; the
  // chip that took its place takes it, else the one before, else the expression input. Found by
  // POSITION, never by label: two chips can read alike, and a label search would land on the wrong
  // one of them.
  const chipsRef = useRef<HTMLDivElement>(null);
  const expressionInputRef = useRef<HTMLInputElement>(null);
  const refocusAfterRemoval = useRef<{index: number} | null>(null);
  const removeFilter = (index: number) => {
    refocusAfterRemoval.current = {index};
    apply({filters: removeFilterItem(query, index).filters});
  };
  // Keyed on the filters, so it runs after the commit that dropped the removed chip.
  useEffect(() => {
    const pending = refocusAfterRemoval.current;
    if (pending === null) return;
    refocusAfterRemoval.current = null;
    const buttons = Array.from(chipsRef.current?.querySelectorAll('button') ?? []);
    const next = buttons[pending.index] ?? buttons[pending.index - 1];
    if (next) next.focus();
    else expressionInputRef.current?.focus();
  }, [query.filters]);

  // The filter already on that column, so re-filtering it is an edit rather than a retype.
  // The dialog decides for itself which half of it to pre-fill from, since a single-value
  // filter leaves list mode empty and a list leaves the single-value field empty.
  const pendingExisting = pendingFilter ? filterOf(query, pendingFilter.column) : null;

  const cursorColumn = geometry.visible.find((column) => column.name === selection.selection.cursor.column) ?? null;
  const cursorRow = selection.selection.cursor.row;
  // THE RAW CELL VALUE, never `cellText` and never a formatted rendering: a
  // NULL reads as "NULL" on screen and a transformed URL will not look like its value at
  // all, and either one as a predicate matches nothing.
  const cursorValue = cursorColumn ? rows[cursorRow]?.[cursorColumn.index] : undefined;

  // Suspended is not loading, and neither is held: nothing is in flight, deliberately. Without
  // this the status line announced "Running…" directly above the panel saying nothing had been
  // run. A banner with no earlier result to show is not loading either — it said "Running…"
  // under a failure.
  const loading =
    !queryControls.suspended &&
    !held &&
    (failed ? shownExecutionId !== null && results.isPending : isPending || !shownExecutionId || results.isPending);

  // `failed` is checked FIRST and is the one that is easy to miss: a failed
  // apply still has a rendered `sql` — the statement Athena rejected — while `shownExecutionId`
  // has fallen back to the last good one, so the grid is showing a DIFFERENT query's rows. A
  // save there writes a file that fails to open in the workspace it promises it opens in.
  // A suspended description needs no clause of its own: the workspace passes `useExploration`
  // nothing while suspended, so `sql` is already null.
  // A statement still running when the watch ended is a statement Athena accepted, so it saves.
  const saveRefusal = failed && !stillRunning ? FAILED_NOT_SAVEABLE : sql === null ? NOTHING_TO_SAVE : null;
  const viewRefusal = failed && !stillRunning ? FAILED_NO_VIEW : sql === null ? NOTHING_TO_VIEW : null;
  const hasCell = cursorColumn !== null && cursorValue !== undefined;
  // Checked in this order because a held tab has no rows and so no cell: its refusal is the true
  // one. The cursor can sit in the calculated column like any other, and this gesture does not go
  // through the header menu, so it asks the same reader the menu does.
  const filterByValueRefusal = held
    ? HELD_FILTER_BY_VALUE_REFUSAL
    : !hasCell
      ? NO_CELL_TO_FILTER
      : actions.filterByValueRefusalOf(cursorColumn.name);

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

  // THE RAW CELL VALUE seeds the list, for the reason `cursorValue` is read raw: a NULL cell
  // ticks NULL, and a value the list could not tick starts nothing ticked.
  const filterByCellValue = () => {
    if (!cursorColumn || cursorValue === undefined) return;
    setFilterByValue({column: cursorColumn.name, seed: {value: cursorValue}});
  };

  const applyFilterByValue = (column: string, result: FilterByValueResult) => {
    setFilterByValue(null);
    if (result.kind === 'clear') actions.clearFilter(column);
    else actions.filter(column, result.operator, {values: result.values, includesNull: result.includesNull});
  };

  const body = () => {
    if (held) {
      const note = leftOutNote(held.leftOut);
      return (
        <div className="flex flex-col items-start gap-2 p-4">
          <p className="text-sm text-text-2">{heldText(held.space)}</p>
          {note && <p className="text-sm text-text-2">{note}</p>}
          <Button
            onClick={() => {
              onRun?.();
              // The button leaves with the hold; focus goes to the filter expression, where the
              // user carries on, rather than to the page body.
              expressionInputRef.current?.focus();
            }}>
            Run
          </Button>
        </div>
      );
    }
    if (queryControls.suspended) {
      return (
        <div className="flex flex-col items-start gap-2 p-4">
          <p className="text-sm text-text-2">{SUSPENDED_TEXT}</p>
          <Button onClick={queryControls.retry}>Run it anyway</Button>
        </div>
      );
    }
    // The banner above has already said this; an empty grid under it would be a second,
    // less true account of the same failure. So would "No rows returned." under a banner with
    // no earlier result to fall back on.
    if (shownExecutionId !== null && results.isError) return null;
    if (failed && shownExecutionId === null) return null;
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
          <ExplorationGrid
            columns={geometry.visible}
            rows={rows}
            rangeStart={results.rangeStart}
            geometry={geometry}
            selection={selection}
            actions={actions}
            formatting={pageFormatting}
            onRequestFilterValue={(column, operator) => setPendingFilter({column, operator})}
            onFilterByValue={(column) => setFilterByValue({column, seed: null})}
            onColumnDrag={(name) => {
              draggedColumn.current = name;
            }}
            onCopy={plainCopy}
            gridRef={gridRef}
          />

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

        <div className="flex flex-none flex-wrap items-center gap-2 px-1">
          <Pager
            hasPrev={results.hasPrev}
            hasNext={results.hasNext}
            onPrev={results.goPrev}
            onNext={results.goNext}
            nextBusy={results.isFetchingNext}
            label={`Rows ${results.rangeStart}–${results.rangeEnd}${totalLabel}`}
            className="min-w-0 flex-1 basis-64"
          />
          {/* The Query workspace's own control, by name and by rule: present only once
              there is a result to save, so the menu item is where the refusal is read. */}
          {saveResultsRefusal === null && (
            <button
              type="button"
              onClick={() => onExport(exportColumns)}
              className="inline-flex h-8 items-center gap-2 rounded-md px-3 text-sm font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4"
                aria-hidden="true">
                <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
                <path d="M9 4v5h6" />
                <path d="M8 21v-7h8v7" />
              </svg>
              Save results…
            </button>
          )}
        </div>
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
        {/* Every action, now — including the three that change the query, which used to sit
            out here as buttons. The bar is left with undo/redo: the controls whose current
            state has to be readable, and which get used repeatedly rather than once per
            decision.

            A REFUSAL SURVIVES THE MOVE. Each of these was `aria-disabled` with a reason on
            the toolbar, and an item that merely greys out inside a menu would be strictly
            worse than the button it replaced — the reason ends up further from the user, not
            closer. They ride `MenuItem.disabledReason`, which exists for exactly this.

            Copy issues nothing and never has (see `renderCopy`) — the plain Ctrl/Cmd+C is on
            the grid, and `Copy…` is the same copy with the formats a destination other than a
            spreadsheet wants. Export is built from the EXECUTION's own results object, so a
            filtered, ordered or grouped exploration exports what is on screen without a
            second query and without a second bill — and since the file holds the columns this
            grid shows, it can be a subset of that object rather than all of it. Its refusal is
            the host's, which knows whether the object exists yet, OR this surface's, which is
            the only thing that knows whether any of the result is on screen. */}
        <ExplorationOptionsMenu
          onOrderAndFilter={() => setSettingsOpen(true)}
          clearAllLabel={queryControls.clearAllLabel}
          onClearAll={queryControls.clearAll}
          clearAllRefusal={queryControls.clearAllRefusal ?? undefined}
          onFilterByValue={filterByCellValue}
          filterByValueRefusal={filterByValueRefusal ?? undefined}
          onColumns={() => setColumnsOpen(true)}
          onColours={() => setColoursOpen(true)}
          onTransformers={() => setTransformersOpen(true)}
          onCopy={() => setCopyOpen(true)}
          onExport={() => onExport(exportColumns)}
          valueOpen={presentation.valuePanelOpen}
          onToggleValue={() => onPresentationChange((p) => ({...p, valuePanelOpen: !p.valuePanelOpen}))}
          calcOpen={calcOpen}
          onToggleCalc={() => setCalcOpen((open) => !open)}
          groupingOpen={groupingOpen}
          onToggleGrouping={() => setGroupingOpen((open) => !open)}
          copyRefusal={selection.selectedCount === 0 ? NOTHING_SELECTED_TO_COPY : undefined}
          exportRefusal={saveResultsRefusal ?? undefined}
          savedQueriesEnabled={queryEnabled}
          onSaveQuery={onSaveQuery}
          saveRefusal={saveRefusal ?? undefined}
          createViewEnabled={queryEnabled}
          onCreateView={onCreateView}
          // A view is made FROM a statement, so this region's own reasons mirror a save's: there is
          // nothing to build one out of. The host's reason is about the SOURCE and comes second.
          createViewRefusal={viewRefusal ?? createViewRefusal ?? undefined}
          openInQueryEnabled={queryEnabled && onOpenInQuery !== undefined}
          onOpenInQuery={() => {
            if (sql !== null) onOpenInQuery?.(sql);
          }}
          openInQueryRefusal={sql === null ? NOTHING_TO_OPEN : undefined}
        />
        {/* The count says "on this page" every time it is said, because that is the only
            thing a selection here can ever mean — Ctrl/Cmd+A included. */}
        <p
          role="status"
          className="text-xs text-text-3">
          {held
            ? 'Not run yet.'
            : loading
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
        inputRef={expressionInputRef}
      />

      {/* The column filters the menus set, which the expression box never shows. They apply
          together with it, and each chip removes its own filter as one apply. */}
      {query.filters.length > 0 && (
        <div
          ref={chipsRef}
          className="flex-none">
          <ChipList ariaLabel="Column filters">
            {/* Keyed by position: nothing else is unique, since two items can read alike. */}
            {query.filters.map((item, index) => (
              <Chip
                key={index}
                name={filterItemLabel(item)}
                removeLabel={chipRemoveLabel(item)}
                onRemove={() => removeFilter(index)}
              />
            ))}
          </ChipList>
        </div>
      )}

      {/* Available whether or not grouping is active: the Explorer writes SQL
          the user did not, grouped or otherwise, and every statement it writes is a bill. */}
      <GeneratedSqlDisclosure
        sql={sql}
        onOpenInQuery={queryEnabled ? onOpenInQuery : undefined}
      />

      {/* One banner at a time, and the exploration's own failure outranks the results
          read: a statement that failed is WHY its rows could not be fetched, and saying
          both names the symptom twice. */}
      {error != null ? (
        <ErrorBanner
          error={error}
          variant={stillRunning ? 'warning' : 'danger'}
        />
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
          existing={pendingExisting}
          onApply={(result) => {
            actions.filter(pendingFilter.column, pendingFilter.operator, result);
            setPendingFilter(null);
          }}
          onCancel={() => setPendingFilter(null)}
        />
      )}

      {filterByValue && source && (
        <FilterByValueDialog
          source={source}
          column={filterByValue.column}
          valueKind={valueKindOf(filterByValue.column)}
          query={query}
          existing={filterOf(query, filterByValue.column)}
          seed={filterByValue.seed}
          onApply={(result) => applyFilterByValue(filterByValue.column, result)}
          onCancel={() => setFilterByValue(null)}
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
