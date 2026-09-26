import {Suspense, lazy, useEffect, useEffectEvent, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {useLocation, useNavigate} from 'react-router';
import {useAuth} from '../auth';
import {useQueryResults} from '../catalog/useQueryResults';
import {useResultsPageSize} from './useResultsPageSize';
import {useResultRowCount} from '../catalog/useResultRowCount';
import {useColumnWidths} from '../catalog/useColumnWidths';
import {useQueryHistory} from './useQueryHistory';
import {useQueryTabs} from './useQueryTabs';
import {useTabRuns} from './useTabRuns';
import {useRunDdl} from '../catalog/useRunDdl';
import {buildCreateViewSql} from '../catalog/createView';
import {sqlDdlIdentifier} from '../../lib/sql';
import {useMobileQuerySurface} from './useMobileQuerySurface';
import {useSaveResults} from '../catalog/useSaveResults';
import {useTableActions} from './useTableActions';
import {useEditorSplit} from './useEditorSplit';
import {EditorSplitDivider} from './EditorSplitDivider';
import {useSavedQueryFlow} from './useSavedQueryFlow';
import {useRefreshLink} from './useRefreshLink';
import {useConnections} from '../connections/useConnections';
import {useFeature} from '../feature-flags';
import {useAllSchemas} from '../catalog/useSchema';
import {
  deriveViewTargetDatabase,
  isExplorableSql,
  resolveRunStatements,
  splitSqlStatements,
  statementHint,
  stripTrailingSemicolons
} from './query.sql';
import {unnamedColumnsRefusal} from './exploreResult';
import {buildExploreSqlHandoff, readOpenSqlHandoff} from '../../lib/routeHandoff';
import {SchemaBrowser} from './SchemaBrowser';
import {QueryMobileView} from './QueryMobileView';
import {QueryResultsMobile} from './QueryResultsMobile';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useTableShare} from '../table-share';
import {useTableRefresh} from '../table-builder';
import {useToast} from '../../components/toastContext';
import {toUserMessage} from '../../lib/errorMessages';
import {QueryHistoryPanel} from './QueryHistoryPanel';
import {SavedQueriesPanel} from './SavedQueriesPanel';
import {QueryTabStrip} from './QueryTabStrip';
import {QueryResultsRegion} from './QueryResultsRegion';
import {QueryToolbar} from './QueryToolbar';
import {QueryDialogs} from './QueryDialogs';
import type {SqlEditorHandle} from './SqlEditor';
import {isConnectionUsable} from '../connections/connection.types';
import type {QueryHistoryEntry, QueryTab} from './query.types';
import type {GlueTableSummary} from '../catalog/catalog.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it.
const SqlEditor = lazy(() => import('./SqlEditor').then((m) => ({default: m.SqlEditor})));

/**
 * The query workspace: schema browser (left) + editor/status/results
 * (main), wired to the catalog data layer. The editor is multi-tab:
 * each tab is an independent query window with its own SQL + run state; Run/Clear/
 * Stop/status/results all act on the active tab.
 *
 * @example
 * <QueryWorkspace />
 */
export function QueryWorkspace() {
  const {user} = useAuth();
  const username = user?.username ?? '';
  // There is no active database. The rail browses every accessible
  // database; queries carry no execution context and must fully-qualify every
  // base table. `useConnections` still enumerates the browsable/queryable spaces.
  // Below `tablet` the workspace is browse-first — no Monaco, no editor
  // toolbar, no tab strip. Mount-gated (not CSS-hidden) because `hidden` would
  // still instantiate the editor (react.md §20).
  const isMobile = useIsMobile();

  const {connections: allConnections, isLoading: connectionsLoading} = useConnections(username || null);
  // Gating (extending the contract table — see the delivery doc): shared spaces are
  // a shared-workspace surface here too. Leaving `teamspace` browsable in the rail while the
  // spaces list and /connections are gone reads as a bug rather than as a policy.
  //
  // FILTERED AT THE VIEW, NEVER AT THE SERVICE: `useConnections` still fetches and resolves
  // every space, because a flag may not touch a service. A saved query
  // naming a hidden database still RUNS — the grants are untouched, and hiding a surface is
  // not revoking access.
  const sharedSpacesEnabled = useFeature('sharedWorkspaces');
  const connections = useMemo(
    () => (sharedSpacesEnabled ? allConnections : allConnections.filter((c) => c.kind === 'personal')),
    [sharedSpacesEnabled, allConnections]
  );
  // Every usable database, for the browse rail + multi-database autocomplete.
  const usableDatabases = useMemo(() => connections.filter(isConnectionUsable).map((c) => c.database), [connections]);
  // Autocomplete offers fully-qualified names across every
  // accessible database (shares the schema cache with the expandable rail nodes).
  // Skipped below `tablet`: its only consumer is the editor's autocomplete, and
  // the editor isn't mounted there — otherwise a phone pays 2 Glue calls per
  // database for a feature it can't reach.
  const completionSchemas = useAllSchemas(isMobile ? [] : usableDatabases);

  // One-time cleanup of the retired active-database sessionStorage key.
  useEffect(() => {
    try {
      const legacyPrefix = 's3portal.query.activeDatabase.';
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith(legacyPrefix)) sessionStorage.removeItem(key);
      }
    } catch {
      // sessionStorage unavailable — nothing to clean up.
    }
  }, []);

  const tabs = useQueryTabs(username);
  const {activeTab, activeTabId} = tabs;

  // The editor+results column is measured (ResizeObserver, guarded for
  // environments without one) and the hook derives the editor pane's clamped
  // pixel height from the dragged fraction.
  const layoutColumnRef = useRef<HTMLDivElement>(null);
  const [layoutColumnHeight, setLayoutColumnHeight] = useState(0);
  useLayoutEffect(() => {
    const el = layoutColumnRef.current;
    if (!el) return;
    setLayoutColumnHeight(el.clientHeight);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => setLayoutColumnHeight(el.clientHeight));
    observer.observe(el);
    return () => observer.disconnect();
    // The column only exists above `tablet`, so a session that starts narrow and
    // widens has to re-measure — a mount-only effect finds no element, returns,
    // and leaves the split permanently unmeasured with no way to move it.
  }, [isMobile]);
  const split = useEditorSplit(username || null, layoutColumnHeight);

  // Drawers are mutually exclusive: opening one closes the other.
  const [historyOpen, setHistoryOpen] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [limitOpen, setLimitOpen] = useState(false);
  const [closing, setClosing] = useState<QueryTab | null>(null);
  // Table actions.
  const [dropping, setDropping] = useState<{database: string; table: GlueTableSummary} | null>(null);
  const toast = useToast();
  // "Share table" dialog + enqueue state (toasts route through the host).
  const share = useTableShare(toast.push);
  // "Refresh table" dialog + enqueue state, wired the same way. The hook also owns the
  // rail invalidation, since the enqueue is the only signal there is; the link a
  // `columns_removed` notification carries is resolved by `useRefreshLink`.
  const refreshLink = useRefreshLink(connections, connectionsLoading);
  const refresh = useTableRefresh(toast.push, {target: refreshLink.target, onConsumed: refreshLink.clear});
  // Create view. The target database is derived from the body.
  const [createViewOpen, setCreateViewOpen] = useState(false);
  const [createViewDb, setCreateViewDb] = useState('');
  const editorRef = useRef<SqlEditorHandle>(null);
  // Monaco carries its own automatic layout, which reacts a frame late; a drag
  // is continuous, so re-measure it as the pane height lands instead.
  useEffect(() => {
    editorRef.current?.layout();
  }, [split.editorHeight]);
  // The list fields feed the mobile browse-first home; the
  // desktop drawer subscribes to the same cache key, so this adds no fetch.
  const {
    history,
    isLoading: historyLoading,
    error: historyError,
    appendEntry,
    updateEntry
  } = useQueryHistory(username || null);
  // Everything the workspace does with saved `.sql` files — the current space, the
  // listing, the folder marker, the dirty markers, the save dialog, open and delete.
  const savedFlow = useSavedQueryFlow({
    username,
    sharedSpacesEnabled,
    tabs,
    toast,
    focusEditor: () => editorRef.current?.focus(),
    onTabLimit: () => setLimitOpen(true),
    onOpened: () => setSavedOpen(false)
  });
  const {savedSpaces, savedSpace, saved, dirtyTabIds, saveQuery} = savedFlow;
  const activeLinkedSaved = activeTab.savedQuery;

  // The whole batch state machine — per-tab runs,
  // the headless pollers, submission, sequential advancement, Stop and the
  // per-tab error bookkeeping — lives in `useTabRuns`.
  const {
    runs,
    statuses,
    runErrors,
    dismissed,
    pollers,
    submitBatch,
    handleStop,
    dropRunState,
    dismissError,
    selectResultTab,
    closeResultTab
  } = useTabRuns({username, activeTabId, tabs: tabs.tabs, appendEntry, updateEntry, toast});

  // Create view and Drop table were the same forty lines twice.
  // One background-DDL path now runs, records and reports both.
  const ddl = useRunDdl({username, appendEntry, toast});

  // The below-`tablet` browse-first surface — its view state, the
  // token that identifies a run it submitted, and the reset on crossing up.
  const mobile = useMobileQuerySurface({isMobile, activeTabId, runs, submitBatch});
  // A local const so the `kind` discriminant narrows inside the render callbacks.
  const mobileView = mobile.view;

  // A statement handed over from the Data Explorer's Generated SQL opens ONCE per history entry —
  // `StrictMode` runs this effect twice on mount, and the replace below lands a render later — in
  // a new tab, unrun: running it is the user's call, as re-opening a history entry is. The entry is
  // replaced with no state whenever the hand-off was read, the tab limit included, so neither a
  // reload nor Back opens a second tab. A phone has no tab strip, so it cannot close a tab to make
  // room: there the read-only view shows the statement whether or not a tab was opened, and the
  // tab-limit dialog, which asks for exactly that, is never raised.
  const location = useLocation();
  const navigate = useNavigate();
  const consumedOpenSql = useRef<string | null>(null);
  const acceptOpenSql = useEffectEvent((handoff: {sql: string; label: string}) => {
    const id = tabs.openTab({label: handoff.label, sql: handoff.sql});
    if (isMobile) mobile.viewSql(handoff.sql, handoff.label);
    else if (id === null) setLimitOpen(true);
    navigate({pathname: location.pathname, search: location.search, hash: location.hash}, {replace: true, state: null});
  });
  useEffect(() => {
    if (consumedOpenSql.current === location.key) return;
    const handoff = readOpenSqlHandoff(location.state);
    if (!handoff) return;
    consumedOpenSql.current = location.key;
    // The history entry is outside React and delivers the hand-off once; opening its tab, or
    // refusing one at the cap, is state that event has to set, which the rule's analysis does not
    // trace through the effect event.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    acceptOpenSql(handoff);
  }, [location.key, location.state]);

  const openHistory = () => {
    setSavedOpen(false);
    setHistoryOpen(true);
  };
  const openSaved = () => {
    setHistoryOpen(false);
    setSavedOpen(true);
  };

  // Active-tab derived run state. In-flight means the BATCH hasn't
  // reached a terminal state (the finalizer sets `done`), not just the current
  // statement's execution.
  const activeRun = runs[activeTabId];
  // A token marks a run the mobile surface submitted, which deliberately leaves
  // the editor buffer alone — so on the editor shell it would pair the tab's
  // draft with results from other SQL entirely. The run itself is untouched (it
  // keeps polling, finalizes, and lands in history); only this shell's status +
  // results display disowns it.
  const editorOwnsRun = activeRun?.token === undefined;
  const activeExecutionId = activeRun?.executionId ?? null;
  const activeStatus = statuses[activeTabId];
  const activeIsInFlight = !!activeRun && !activeRun.done;
  const activeBatchDone = !!activeRun?.done;

  // Which execution the results region displays once the batch
  // settles — the active result tab in the tab-per-statement scope, else the
  // LAST result-producing statement. A sole succeeded statement that produced
  // no rows (DDL) falls back to its own execution so today's single-statement
  // behavior (empty grid) is preserved exactly.
  const displayedResultTab = (() => {
    if (!activeRun || !activeRun.done) return null;
    if (activeRun.scope === 'script-tabs') return activeRun.resultTabs[activeRun.activeResultTabIndex] ?? null;
    return activeRun.resultTabs.length > 0 ? activeRun.resultTabs[activeRun.resultTabs.length - 1] : null;
  })();
  const soleStatementSucceeded =
    activeBatchDone && activeRun.statements.length === 1 && activeStatus?.state === 'SUCCEEDED';
  const displayExecutionId = displayedResultTab?.executionId ?? (soleStatementSucceeded ? activeRun.executionId : null);
  // A displayed result tab ANSWERS for its own output object rather than falling through:
  // `??` would hand Save-results a different execution's CSV if a captured status ever
  // arrived without one, and the fallthrough also hid a dropped capture from the save tests.
  const displayOutputLocation = displayedResultTab
    ? displayedResultTab.status.outputLocation
    : activeStatus?.outputLocation;

  // The status the bar narrates. Its scanned/duration figures sit in the same
  // sentence as the row count, which follows `displayExecutionId` — so reading them off
  // the editor tab's status paired one statement's rows with another's bytes, with
  // nothing on screen saying they came from different executions.
  //
  // Only a SUCCEEDED batch swaps. A failure or a Stop keeps its own verdict: the bar's
  // indicator is the only terminal signal left once the user dismisses the banner, and a
  // batch that failed at statement 3 still displays statement 1's succeeded result tab.
  const displayStatus =
    activeStatus?.state === 'SUCCEEDED' && displayedResultTab ? displayedResultTab.status : activeStatus;

  // The Save-results dialog, its destination list, the overwrite
  // warn-and-confirm and the default file name.
  //
  // The destinations are `savedSpaces` — the SAME view-gated list every other
  // space selector on this page uses. The hook used to build its own from an unfiltered
  // `useQuerySpaces()`, which left this one dialog offering a colleague's space as a write
  // target with `sharedWorkspaces` off; it now has a registry row of its own.
  const saveResults = useSaveResults({
    spaces: savedSpaces,
    username,
    outputLocation: displayOutputLocation,
    // The execution `displayOutputLocation` was derived from, so a conversion converts the
    // result that is on screen rather than the batch's last statement.
    executionId: displayExecutionId,
    linkedSavedName: activeLinkedSaved?.name,
    // This grid hides nothing and reorders nothing, so a save from here is always the whole
    // result in its own order — which is what null means, and what keeps CSV an instant copy.
    columnIndexes: null,
    toast
  });
  // What the EDITOR shell may show: never a run the mobile surface submitted
  // (those carry a token and leave the editor buffer untouched by design).
  const editorExecutionId = editorOwnsRun ? activeExecutionId : null;
  const editorDisplayExecutionId = editorOwnsRun ? displayExecutionId : null;
  const showResultTabs =
    editorOwnsRun && activeRun?.scope === 'script-tabs' && activeBatchDone && activeRun.resultTabs.length > 0;

  // Results only fetch once the batch has settled on a displayable execution;
  // one page at a time via the pager, sized by the workspace-global
  // "Rows per page" value — one shared value for every result tab.
  const resultsPageSize = useResultsPageSize(username || null);
  const results = useQueryResults(displayExecutionId, resultsPageSize.pageSize);

  // Exact total row count — Athena's own count, or a page walk where Athena does not count —
  // scoped to the execution id so a new run / result-tab switch recomputes.
  //
  // Opened by the BATCH's verdict, not by the arrival of the first page. A result tab is
  // only ever created for a statement that produces rows, so its presence says so before
  // any page comes back — and the count is a separate request that never needed the display
  // fetch. Waiting for `columns` made the total two chained round-trips late on a first run
  // and made it vanish and re-count on every flip between statements, because the newly
  // selected execution has no columns yet.
  //
  // `columns.length > 0` stays as a second opener rather than being replaced: a statement
  // the batch did not classify as row-returning, but which returned columns anyway, counted
  // before and still does. DDL opens neither, so nothing is asked for it.
  const hasResultSet = displayExecutionId !== null && results.columns.length > 0;
  const producesRows = displayedResultTab !== null || results.columns.length > 0;
  const rowCount = useResultRowCount(displayExecutionId !== null && producesRows ? displayExecutionId : null);

  // The one total the status bar and both pagers show, and it never contradicts the grid.
  // The pager's own count wins once it holds the last page, because it counts the rows the
  // grid actually has; it is read only with a result set present, since before the first page
  // it reads 0. Otherwise the count is shown only while it is at least the rows already
  // loaded: a smaller number is not a total, whatever produced it.
  const pagerTotal = hasResultSet ? results.totalRowCount : null;
  const shownTotal =
    pagerTotal ?? (rowCount.total !== null && rowCount.total >= results.loadedRowCount ? rowCount.total : null);

  // Result-column widths, keyed by execution id. Lives here (not in
  // QueryResultsTable, which unmounts when the active tab has no results) so a
  // user's resizes survive Prev/Next AND query/result-tab switches; a new query
  // (new execution id) starts from defaults.
  const colWidths = useColumnWidths(displayExecutionId, results.columns.length);

  // Run Statement — the selection, else the statement under the
  // cursor, else the sole statement. When the editor handle isn't available
  // (still lazy-loading), the cursor defaults to the buffer end (last statement).
  //
  // A selection holding several statements runs with the tab-per-statement scope: the scopes
  // differ only in how results are shown, and showing only the last of several statements the
  // user picked out hides every result but one.
  const handleRunStatement = () => {
    const buffer = activeTab.sql;
    const statements = splitSqlStatements(buffer);
    const selection = editorRef.current?.getSelectionRange() ?? null;
    const cursor = editorRef.current?.getCursorOffset() ?? buffer.length;
    const resolved = resolveRunStatements(buffer, statements, selection, cursor);
    submitBatch(resolved, resolved.length > 1 ? 'script-tabs' : 'statement');
  };

  // Run Script — every statement in the buffer, sequentially.
  const handleRunScript = (scope: 'script-single' | 'script-tabs') =>
    submitBatch(splitSqlStatements(activeTab.sql), scope);

  // re-open loads the entry's SQL into the active
  // tab's editor (no auto-run); re-run loads it and submits.
  const handleReopen = (entry: QueryHistoryEntry) => {
    tabs.setActiveSql(entry.sql);
    setHistoryOpen(false);
    editorRef.current?.focus();
  };
  const handleRerun = (entry: QueryHistoryEntry) => {
    if (activeIsInFlight) return;
    tabs.setActiveSql(entry.sql);
    setHistoryOpen(false);
    submitBatch(splitSqlStatements(entry.sql), 'script-single');
  };

  // Open a tab through the cap guard; at the cap show the dialog.
  const handleNewTab = () => {
    const id = tabs.openTab();
    if (id === null) setLimitOpen(true);
    else editorRef.current?.focus();
  };

  const requestClose = (id: string) => {
    const tab = tabs.tabs.find((t) => t.id === id);
    if (!tab) return;
    if (tab.sql.trim()) {
      setClosing(tab); // non-empty → confirm first
    } else {
      tabs.closeTab(id);
      dropRunState(id);
    }
  };
  const confirmClose = () => {
    if (!closing) return;
    const id = closing.id;
    tabs.closeTab(id);
    dropRunState(id);
    setClosing(null);
  };

  // Derive the target database from the view body before opening the
  // dialog; a non-derivable body raises a clear error and never silently picks
  // a database.
  const handleOpenCreateView = () => {
    const target = deriveViewTargetDatabase(stripTrailingSemicolons(activeTab.sql));
    if ('error' in target) {
      toast.push({variant: 'danger', message: target.error});
      return;
    }
    setCreateViewDb(target.database);
    setCreateViewOpen(true);
  };

  const handleClearConfirm = () => {
    tabs.clearActive();
    setClearOpen(false);
    editorRef.current?.focus();
  };

  // The per-table rail actions, and the mobile nav-rail copy
  // that has to be fed the same handlers.
  const tableActions = useTableActions({
    username,
    isMobile,
    connections,
    toast,
    mobile,
    submitBatch,
    openTab: tabs.openTab,
    onTabLimit: () => setLimitOpen(true),
    focusEditor: () => editorRef.current?.focus(),
    onRefreshTable: refresh.open,
    onShareTable: share.open,
    onDropTable: setDropping
  });

  // Turn the active tab's SQL into a named view, in the background
  // (the editor keeps showing the user's SELECT). The target database is derived
  // from the view body's fully-qualified base tables, captured in
  // `createViewDb` when the dialog opened.
  const handleCreateView = (name: string) => {
    const database = createViewDb;
    if (!database) return;
    ddl.run({
      sql: buildCreateViewSql(database, name, activeTab.sql),
      database,
      table: name,
      describe: {success: `Created view ${name}`, failure: `Couldn\u2019t create view ${name}.`},
      onSettled: () => setCreateViewOpen(false)
    });
  };

  // Drop the rail's table or view, recorded in history like any
  // other statement.
  const handleDropConfirm = () => {
    if (!dropping) return;
    const {database, table} = dropping;
    const isView = table.tableType === 'VIRTUAL_VIEW';
    ddl.run({
      // Backticks, not double quotes: a DROP is DDL, which Athena parses with Hive. The
      // database is the identifier that needs it — a shared space named before the control
      // plane took the catalog rule passed no server-side format check.
      sql: `DROP ${isView ? 'VIEW' : 'TABLE'} ${sqlDdlIdentifier(database)}.${sqlDdlIdentifier(table.name)}`,
      database,
      table: table.name,
      describe: {success: `Dropped ${table.name}`, failure: `Couldn\u2019t drop ${table.name}.`},
      onSettled: () => setDropping(null)
    });
  };

  // a batch that ended early names the statement it ended at and
  // makes clear the remaining statements did not run. A lone statement is
  // just its reason.
  const endedBatchMessage = (statements: number, statementIndex: number, what: string, reason: string) => {
    if (statements === 1) return reason;
    const at = statementIndex + 1;
    const skipped = statements - at;
    const skippedNote =
      skipped === 0
        ? ''
        : skipped === 1
          ? ` Statement ${statements} did not run.`
          : ` Statements ${at + 1}–${statements} did not run.`;
    return `Statement ${at} of ${statements} ${what}. ${reason}${skippedNote}`;
  };
  const batchFailureMessage = activeRun?.failure
    ? endedBatchMessage(
        activeRun.statements.length,
        activeRun.failure.statementIndex,
        'failed',
        activeRun.failure.reason
      )
    : null;
  const stillRunning = activeRun?.stillRunning;
  const stillRunningMessage = stillRunning
    ? endedBatchMessage(
        activeRun.statements.length,
        stillRunning.statementIndex,
        'is still running',
        stillRunning.message.message
      )
    : null;
  const statusFailure =
    activeStatus?.state === 'FAILED'
      ? toUserMessage({code: activeStatus.state, message: activeStatus.stateChangeReason})
      : null;
  // One chain picks both halves, so a Details disclosure can never belong to a different error
  // than the sentence above it.
  const shownError: {message: string; detail?: string} | null =
    runErrors[activeTabId] != null
      ? {message: runErrors[activeTabId]}
      : batchFailureMessage !== null
        ? {message: batchFailureMessage, detail: activeRun?.failure?.detail}
        : stillRunningMessage !== null
          ? {message: stillRunningMessage}
          : statusFailure;
  const errorMessage = shownError?.message ?? null;
  const errorDetail = shownError?.detail;
  // The banner's title and colour follow the message it shows. A statement the browser stopped
  // watching did not fail, so its banner is a warning under the rule's own title; anything that
  // outranks it (a start that failed) keeps the failure's.
  const errorBanner =
    stillRunning && !runErrors[activeTabId] && batchFailureMessage === null
      ? {errorTitle: stillRunning.message.title, errorVariant: 'warning' as const}
      : {};
  // A failed start is the latest submit's own news, so a dismissal does not hide it — the
  // dismissal belongs to the run still on the tab, and holds until the next run replaces it.
  const showError = !!errorMessage && (!!runErrors[activeTabId] || !dismissed[activeTabId]);
  const canRun = !!activeTab.sql.trim() && !activeIsInFlight;
  const canClear = activeTab.sql.length > 0 && !activeIsInFlight;
  const canSave = !!activeTab.sql.trim(); // disabled only when empty

  // Savable = a row-returning result object (not a DDL / no-result statement) belonging
  // to the DISPLAYED result tab. Deliberately blind to the run's verdict: a batch that
  // failed at a later statement leaves an earlier one's result complete and already paid for.
  const canSaveResults = displayExecutionId !== null && !!displayOutputLocation && results.columns.length > 0;

  // Explore in Data Explorer: on Save's terms — the displayed result, whatever the verdict, once
  // its columns have arrived, since the columns are what decide whether it can be explored at all
  // — for a statement the Explorer can wrap. A Data Explorer capability on a Query surface, so
  // both flags gate it. The statement is the one the RUN holds, never the buffer, which may have
  // changed since. A run the mobile surface submitted needs no clause here: the bar carrying the
  // control is not mounted for a run the editor does not own.
  const queryEnabled = useFeature('query');
  const explorerEnabled = useFeature('dataExplorer');
  const displayedStatement =
    displayedResultTab && activeRun ? activeRun.statements[displayedResultTab.statementIndex] : undefined;
  const explore =
    queryEnabled &&
    explorerEnabled &&
    displayedStatement !== undefined &&
    isExplorableSql(displayedStatement.sql) &&
    results.columns.length > 0
      ? {
          disabledReason: unnamedColumnsRefusal(results.columns),
          onExplore: () =>
            navigate('/explore', {
              state: buildExploreSqlHandoff({
                body: stripTrailingSemicolons(displayedStatement.sql),
                label: statementHint(displayedStatement.sql)
              })
            })
        }
      : null;

  return (
    // Cap the workspace to the viewport (minus the h-14 header) so the results
    // pane scrolls internally instead of growing the page (feedback 2026-06-30).
    // Bounding the height here + `min-h-0` down the flex chain is what lets the
    // `overflow-auto` results region actually scroll; the schema rail already
    // scrolls itself (`overflow-y-auto`).
    <div className="flex h-[calc(100dvh-3.5rem)] min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* on a phone the rail lives in the nav drawer instead. */}
      {!isMobile && (
        <SchemaBrowser
          connections={connections}
          actions={tableActions}
        />
      )}

      {pollers}

      <main
        id="main"
        className="flex min-h-0 min-w-0 flex-1 flex-col">
        {isMobile ? (
          mobileView.kind === 'home' ? (
            <QueryMobileView
              tab={mobile.homeTab}
              onTabChange={mobile.setHomeTab}
              spaces={savedSpace.spaces}
              space={savedSpace.space}
              onSelectSpace={savedSpace.selectSpace}
              savedQueries={saved.queries}
              savedLoading={saved.isLoading}
              savedError={saved.error}
              savedHasMore={saved.hasMore}
              onLoadMoreSaved={saved.loadMore}
              savedLoadingMore={saved.isLoadingMore}
              onDeleteSaved={savedFlow.deleteSaved}
              history={history}
              historyLoading={historyLoading}
              historyError={historyError}
              onRun={mobile.runSql}
              onView={mobile.viewSql}
              onRunSaved={(q) => savedFlow.withSavedSql(q, mobile.runSql)}
              onViewSaved={(q) => savedFlow.withSavedSql(q, mobile.viewSql)}
              runDisabled={activeIsInFlight || mobile.pending}
            />
          ) : (
            <QueryResultsMobile
              title={mobileView.title}
              sql={mobileView.sql}
              onBack={mobile.back}
              onRun={() => mobile.runSql(mobileView.sql, mobileView.title)}
              runDisabled={activeIsInFlight || mobile.pending}
              status={mobile.ownsRun ? displayStatus : undefined}
              isInFlight={mobile.pending || (mobile.ownsRun && activeIsInFlight)}
              startedAt={mobile.ownsRun ? (activeRun?.startedAt ?? null) : null}
              hasResultSet={mobile.ownsRun && hasResultSet}
              totalRowCount={mobile.ownsRun ? shownTotal : null}
              countingRows={mobile.ownsRun && rowCount.isCounting}
              hasRun={mobile.ownsRun || mobile.pending}
              batchFailed={mobile.ownsRun && !!activeRun?.failure}
              stillRunning={mobile.ownsRun && !!activeRun?.stillRunning}
              errorMessage={
                mobile.failedToStart ? (mobile.run?.error ?? null) : mobile.ownsRun && showError ? errorMessage : null
              }
              errorDetail={!mobile.failedToStart && mobile.ownsRun && showError ? errorDetail : undefined}
              {...(mobile.failedToStart ? {} : errorBanner)}
              onDismissError={() => {
                // A submit that never started owns its error outright; anything
                // else is the tab's run reporting a failure.
                if (mobile.failedToStart) mobile.clearRun();
                else dismissError(activeTabId);
              }}
              results={results}
              displayExecutionId={mobile.ownsRun ? displayExecutionId : null}
            />
          )
        ) : (
          <>
            <h1 className="sr-only">Query workspace</h1>
            <QueryTabStrip
              tabs={tabs.tabs}
              activeTabId={activeTabId}
              dirtyTabIds={dirtyTabIds}
              onSelect={tabs.setActiveTab}
              onClose={requestClose}
              onNew={handleNewTab}
              onOpenSaved={openSaved}
              onOpenHistory={openHistory}
            />

            {/* The active tab's content (toolbar + editor + results) is the
            tablist's panel, labelled by the active tab (WCAG 4.1.2). */}
            <div
              role="tabpanel"
              id="query-tabpanel"
              aria-labelledby={`query-tab-${activeTabId}`}
              className="flex min-h-0 min-w-0 flex-1 flex-col">
              <QueryToolbar
                isInFlight={activeIsInFlight}
                canRun={canRun}
                canClear={canClear}
                canSave={canSave}
                sql={activeTab.sql}
                onClear={() => setClearOpen(true)}
                onSave={saveQuery.openDialog}
                onCreateView={handleOpenCreateView}
                onStop={handleStop}
                onRunStatement={handleRunStatement}
                onRunScript={handleRunScript}
              />

              {/* the measured editor+results column, and exactly three flex
              children: the editor pane at the split's clamped height, the
              divider, and the results region taking the remainder and
              scrolling internally. */}
              <div
                ref={layoutColumnRef}
                className="flex min-h-0 min-w-0 flex-1 flex-col">
                <div
                  className="flex-none"
                  style={{height: split.editorHeight}}>
                  <Suspense
                    fallback={
                      <div className="flex h-full items-center justify-center bg-surface-2 text-sm text-text-3">
                        Loading editor&hellip;
                      </div>
                    }>
                    <SqlEditor
                      ref={editorRef}
                      tabId={activeTab.id}
                      tabIds={tabs.tabs.map((t) => t.id)}
                      value={activeTab.sql}
                      onChange={tabs.setActiveSql}
                      onRun={handleRunStatement}
                      onRunScriptSingle={() => handleRunScript('script-single')}
                      onRunScriptTabs={() => handleRunScript('script-tabs')}
                      completionSchemas={completionSchemas}
                    />
                  </Suspense>
                </div>

                <EditorSplitDivider
                  {...split.dividerProps}
                  onStep={split.step}
                />

                <div className="flex min-h-0 flex-1 flex-col">
                  <QueryResultsRegion
                    run={activeRun}
                    status={displayStatus}
                    isInFlight={activeIsInFlight}
                    batchDone={activeBatchDone}
                    editorOwnsRun={editorOwnsRun}
                    editorExecutionId={editorExecutionId}
                    editorDisplayExecutionId={editorDisplayExecutionId}
                    displayExecutionId={displayExecutionId}
                    hasResultSet={hasResultSet}
                    totalRowCount={shownTotal}
                    countingRows={rowCount.isCounting}
                    results={results}
                    pageSize={resultsPageSize}
                    colWidths={colWidths}
                    showResultTabs={showResultTabs}
                    showError={showError}
                    errorMessage={errorMessage}
                    errorDetail={errorDetail}
                    {...errorBanner}
                    onDismissError={() => dismissError(activeTabId)}
                    onSelectResultTab={(index) => selectResultTab(activeTabId, index)}
                    onCloseResultTab={(index) => closeResultTab(activeTabId, index)}
                    canSaveResults={canSaveResults}
                    onSaveResults={saveResults.openDialog}
                    explore={explore}
                  />
                </div>
              </div>
            </div>
          </>
        )}
      </main>

      {/* Editor-shell drawers: opened from the tab strip, and their actions
          (Open / Re-run) load SQL into the editor — so they belong to the
          editor's breakpoints only. The mobile home is the surface for these
          two lists below `tablet`. */}
      {!isMobile && (
        <>
          <QueryHistoryPanel
            open={historyOpen}
            onClose={() => setHistoryOpen(false)}
            username={username}
            onReopen={handleReopen}
            onRerun={handleRerun}
            rerunDisabled={activeIsInFlight}
          />

          <SavedQueriesPanel
            open={savedOpen}
            onClose={() => setSavedOpen(false)}
            spaces={savedSpace.spaces}
            space={savedSpace.space}
            onSelectSpace={savedSpace.selectSpace}
            queries={saved.queries}
            isLoading={saved.isLoading}
            error={saved.error}
            hasMore={saved.hasMore}
            onLoadMore={saved.loadMore}
            isLoadingMore={saved.isLoadingMore}
            onRetry={saved.refresh}
            onOpen={savedFlow.openSaved}
            onDelete={savedFlow.deleteSaved}
          />
        </>
      )}

      <QueryDialogs
        clear={{open: clearOpen, onConfirm: handleClearConfirm, onCancel: () => setClearOpen(false)}}
        save={saveQuery}
        closing={{tab: closing, onConfirm: confirmClose, onCancel: () => setClosing(null)}}
        tabLimit={{open: limitOpen, onDismiss: () => setLimitOpen(false)}}
        createView={{
          open: createViewOpen,
          busy: ddl.busy,
          targetDatabase: createViewDb,
          onCreate: handleCreateView,
          onCancel: () => setCreateViewOpen(false)
        }}
        drop={{target: dropping, busy: ddl.busy, onConfirm: handleDropConfirm, onCancel: () => setDropping(null)}}
        share={share}
        refresh={refresh}
        saveResults={saveResults}
      />
    </div>
  );
}
