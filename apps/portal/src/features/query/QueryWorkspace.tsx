import {Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {useLocation, useSearchParams} from 'react-router';
import {useAuth} from '../auth';
import {cx} from '../../lib/cx';
import {spaceBuckets} from '../../lib/userSpace';
import {useQueryResults} from './useQueryResults';
import {useResultsPageSize} from './useResultsPageSize';
import {useResultRowCount} from './useResultRowCount';
import {useColumnWidths} from './useColumnWidths';
import {useQueryHistory} from './useQueryHistory';
import {useQueryTabs} from './useQueryTabs';
import {useTabRuns} from './useTabRuns';
import {useRunDdl} from './useRunDdl';
import {useMobileQuerySurface} from './useMobileQuerySurface';
import {useSaveResults} from './useSaveResults';
import {useTableActions} from './useTableActions';
import {useEditorLayout} from './useEditorLayout';
import {useSavedQueries} from './useSavedQueries';
import {useConnections} from '../connections/useConnections';
import {useAllSchemas, useSchema} from './useSchema';
import {
  deriveViewTargetDatabase,
  resolveRunStatements,
  sameSql,
  splitSqlStatements,
  stripTrailingSemicolons
} from './query.sql';
import {SchemaBrowser} from './SchemaBrowser';
import {QueryMobileView} from './QueryMobileView';
import {QueryResultsMobile} from './QueryResultsMobile';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useTableShare} from '../table-share';
import {parseRefreshLink, useTableRefresh} from '../table-builder';
import {useToast} from '../../components/toastContext';
import {logBackgroundFailure, toUserText} from '../../lib/errorMessages';
import {QueryHistoryPanel} from './QueryHistoryPanel';
import {SavedQueriesPanel} from './SavedQueriesPanel';
import {QueryTabStrip} from './QueryTabStrip';
import {QueryResultsRegion} from './QueryResultsRegion';
import {QueryToolbar} from './QueryToolbar';
import {QueryDialogs} from './QueryDialogs';
import type {SqlEditorHandle} from './SqlEditor';
import {isConnectionUsable} from '../connections/connection.types';
import type {QueryHistoryEntry, QueryTab, SavedQuery, GlueTableSummary} from './query.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it (SPEC-035 FR-003).
const SqlEditor = lazy(() => import('./SqlEditor').then((m) => ({default: m.SqlEditor})));

// SPEC-035 query workspace (FR-002): schema browser (left) + editor/status/results
// (main), wired to the SPEC-034 data layer. SPEC-041 makes the editor multi-tab:
// each tab is an independent query window with its own SQL + run state; Run/Clear/
// Stop/status/results all act on the active tab.
export function QueryWorkspace() {
  const {user} = useAuth();
  const username = user?.username ?? '';
  // SPEC-049: the user-space bucket (also where Athena writes results) — the
  // Save-results copy stays within it. SPEC-055: the shared-space bucket (where
  // shared-DB results land + a Save target).
  const {user: userSpaceBucket, shared: sharedSpaceBucket} = spaceBuckets();

  // SPEC-077: there is no active database. The rail browses every accessible
  // database; queries carry no execution context and must fully-qualify every
  // base table. `useConnections` still enumerates the browsable/queryable spaces.
  // SPEC-100: below `tablet` the workspace is browse-first — no Monaco, no editor
  // toolbar, no tab strip. Mount-gated (not CSS-hidden) because `hidden` would
  // still instantiate the editor (react.md §20).
  const isMobile = useIsMobile();

  const {connections, isLoading: connectionsLoading} = useConnections(username || null);
  // Every usable database, for the browse rail + multi-database autocomplete.
  const usableDatabases = useMemo(() => connections.filter(isConnectionUsable).map((c) => c.database), [connections]);
  // SPEC-077 FR-005: autocomplete offers fully-qualified names across every
  // accessible database (shares the schema cache with the expandable rail nodes).
  // Skipped below `tablet`: its only consumer is the editor's autocomplete, and
  // the editor isn't mounted there — otherwise a phone pays 2 Glue calls per
  // database for a feature it can't reach (SPEC-100).
  const completionSchemas = useAllSchemas(isMobile ? [] : usableDatabases);

  // One-time cleanup of the retired SPEC-047 active-database sessionStorage key.
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

  // SPEC-079: the editor/results layout preset. The editor+results column is
  // measured (ResizeObserver, guarded for environments without one) and the
  // hook derives the editor pane's clamped pixel height from the preset.
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
  }, []);
  const layout = useEditorLayout(username || null, layoutColumnHeight);
  // Ease the editor/results split only when the user picks a preset — never on
  // the ResizeObserver-driven height changes from window resize, which would
  // otherwise make the panes lag behind the viewport.
  const [animateSplit, setAnimateSplit] = useState(false);
  const handleLayoutChange = useCallback(
    (next: Parameters<typeof layout.setPreset>[0]) => {
      setAnimateSplit(true);
      layout.setPreset(next);
    },
    [layout]
  );

  // Drawers are mutually exclusive (FR-010): opening one closes the other.
  const [historyOpen, setHistoryOpen] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [limitOpen, setLimitOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [closing, setClosing] = useState<QueryTab | null>(null);
  // SPEC-044 table actions.
  const [dropping, setDropping] = useState<{database: string; table: GlueTableSummary} | null>(null);
  const toast = useToast();
  // SPEC-093: "Share table" dialog + enqueue state (toasts route through the host).
  const share = useTableShare(toast.push);
  // SPEC-145: "Refresh table" dialog + enqueue state, wired the same way. The hook
  // also owns the rail invalidation, since the enqueue is the only signal there is.
  // SPEC-145 FR-005: `/query?refreshTable={db}.{table}&removed={names}` — the link
  // SPEC-144's `columns_removed` notification carries. Read from the RAW query string
  // (`location.search`), never through `useSearchParams`: that decodes, and the names
  // are individually percent-encoded around a comma separator, so a column named
  // `a,b` would arrive already split.
  //
  // The dialog is DERIVED from the URL rather than opened from an effect (react.md
  // §3, and React Compiler forbids the setState-in-effect that opening would need):
  // acting on it retires the parameters, which is what closes it.
  const location = useLocation();
  const [, setSearchParams] = useSearchParams();
  const link = useMemo(() => parseRefreshLink(location.search), [location.search]);
  // A database the user can't reach resolves to null and is never fetched — no
  // existence oracle, and the rail is the authority on what exists (FR-005).
  const linkDatabase =
    link && !connectionsLoading && connections.some((c) => c.database === link.database && isConnectionUsable(c))
      ? link.database
      : null;
  const {data: linkSchema} = useSchema(linkDatabase);
  const linkTarget = useMemo(() => {
    if (!link || !linkSchema) return null;
    // A view has no folder to re-read and a table with no location can't be turned
    // into a request (FR-001 disables the menu item for the same reason), so a link
    // naming either opens nothing.
    const table = linkSchema.tables.find(
      (t) => t.name === link.tableName && t.tableType !== 'VIRTUAL_VIEW' && !!t.location
    );
    if (!table) return null;
    // A link carrying no names is NOT the link-borne state. That state gates confirm
    // behind the removals opt-in, which is only an informed choice when the columns
    // are named — with an empty list it would coerce a blind `allowRemovals: true`.
    // `tbcommon.notify` mints no link without names; a URL that has one was edited.
    return {database: link.database, table, pending: link.columns.length > 0 ? link : null};
  }, [link, linkSchema]);
  const clearRefreshLink = useCallback(
    () =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('refreshTable');
          next.delete('removed');
          return next;
        },
        {replace: true}
      ),
    [setSearchParams]
  );

  const refresh = useTableRefresh(toast.push, {target: linkTarget, onConsumed: clearRefreshLink});
  // SPEC-048: Create view. SPEC-077: the target database derived from the body.
  const [createViewOpen, setCreateViewOpen] = useState(false);
  const [createViewDb, setCreateViewDb] = useState('');
  const editorRef = useRef<SqlEditorHandle>(null);
  // The list fields feed the mobile browse-first home (SPEC-100 FR-004); the
  // desktop drawer subscribes to the same cache key, so this adds no fetch.
  const {
    history,
    isLoading: historyLoading,
    error: historyError,
    appendEntry,
    updateEntry
  } = useQueryHistory(username || null);
  const saved = useSavedQueries(username || null);

  // SPEC-043 FR-008: a linked tab is "dirty" when its editor SQL differs from the
  // stored saved query. Drives the tab-strip marker. Derived in render (not state),
  // memoized on their real inputs so the Map/Set aren't rebuilt every render (SPEC-083 FR-007).
  const savedById = useMemo(() => new Map(saved.queries.map((q) => [q.id, q])), [saved.queries]);
  const dirtyTabIds = useMemo(
    () =>
      new Set(
        tabs.tabs
          .filter((t) => {
            const sq = t.savedQueryId ? savedById.get(t.savedQueryId) : undefined;
            return sq !== undefined && !sameSql(sq.sql, t.sql);
          })
          .map((t) => t.id)
      ),
    [tabs.tabs, savedById]
  );
  const activeLinkedSaved = useMemo(
    () => (activeTab.savedQueryId ? savedById.get(activeTab.savedQueryId) : undefined),
    [activeTab.savedQueryId, savedById]
  );

  // SPEC-155 FR-009: the whole SPEC-041/078 batch state machine — per-tab runs,
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
    selectResultTab
  } = useTabRuns({username, activeTabId, tabs: tabs.tabs, savedById, appendEntry, updateEntry});

  // SPEC-155 FR-009: Create view and Drop table were the same forty lines twice.
  // One background-DDL path now runs, records and reports both.
  const ddl = useRunDdl({username, appendEntry, toast});

  // SPEC-100: the below-`tablet` browse-first surface — its view state, the
  // token that identifies a run it submitted, and the reset on crossing up.
  const mobile = useMobileQuerySurface({isMobile, activeTabId, runs, submitBatch});
  // A local const so the `kind` discriminant narrows inside the render callbacks.
  const mobileView = mobile.view;

  const openHistory = () => {
    setSavedOpen(false);
    setHistoryOpen(true);
  };
  const openSaved = () => {
    setHistoryOpen(false);
    setSavedOpen(true);
  };

  // Active-tab derived run state. SPEC-078: in-flight means the BATCH hasn't
  // reached a terminal state (the finalizer sets `done`), not just the current
  // statement's execution.
  const activeRun = runs[activeTabId];
  // A token marks a run the mobile surface submitted, which deliberately leaves
  // the editor buffer alone — so on the editor shell it would pair the tab's
  // draft with results from other SQL entirely. The run itself is untouched (it
  // keeps polling, finalizes, and lands in history); only this shell's status +
  // results display disowns it (SPEC-100 review).
  const editorOwnsRun = activeRun?.token === undefined;
  const activeExecutionId = activeRun?.executionId ?? null;
  const activeStatus = statuses[activeTabId];
  const activeIsInFlight = !!activeRun && !activeRun.done;
  const activeBatchDone = !!activeRun?.done;

  // SPEC-078 FR-007: which execution the results region displays once the batch
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
  const displayOutputLocation = displayedResultTab?.outputLocation ?? activeStatus?.outputLocation;

  // SPEC-049/055: the Save-results dialog, its destination list, the overwrite
  // warn-and-confirm and the default file name.
  const saveResults = useSaveResults({
    username,
    userSpaceBucket,
    sharedSpaceBucket,
    connections,
    outputLocation: displayOutputLocation,
    linkedSavedName: activeLinkedSaved?.name,
    toast
  });
  // What the EDITOR shell may show: never a run the mobile surface submitted
  // (those carry a token and leave the editor buffer untouched by design).
  const editorExecutionId = editorOwnsRun ? activeExecutionId : null;
  const editorDisplayExecutionId = editorOwnsRun ? displayExecutionId : null;
  const showResultTabs =
    editorOwnsRun && activeRun?.scope === 'script-tabs' && activeBatchDone && activeRun.resultTabs.length > 0;

  // Results only fetch once the batch has settled on a displayable execution;
  // one page at a time via the SPEC-038 pager, sized by the workspace-global
  // "Rows per page" value (SPEC-087) — one shared value for every result tab.
  const resultsPageSize = useResultsPageSize(username || null);
  const results = useQueryResults(displayExecutionId, resultsPageSize.pageSize);

  // SPEC-080: exact total row count via a background page-walk. Gated on a result
  // set actually existing (columns present) so DDL/no-result statements show no
  // row-count stat; scoped to the execution id so a new run / tab switch recomputes.
  const hasResultSet = displayExecutionId !== null && results.columns.length > 0;
  const rowCount = useResultRowCount(hasResultSet ? displayExecutionId : null);

  // SPEC-064: result-column widths, keyed by execution id. Lives here (not in
  // QueryResultsTable, which unmounts when the active tab has no results) so a
  // user's resizes survive Prev/Next AND query/result-tab switches; a new query
  // (new execution id) starts from defaults.
  const colWidths = useColumnWidths(displayExecutionId, results.columns.length);

  // FR-005/006: Run Statement — the selection, else the statement under the
  // cursor, else the sole statement. When the editor handle isn't available
  // (still lazy-loading), the cursor defaults to the buffer end (last statement).
  const handleRunStatement = () => {
    const buffer = activeTab.sql;
    const statements = splitSqlStatements(buffer);
    const selection = editorRef.current?.getSelectionRange() ?? null;
    const cursor = editorRef.current?.getCursorOffset() ?? buffer.length;
    submitBatch(resolveRunStatements(buffer, statements, selection, cursor), 'statement');
  };

  // FR-005: Run Script — every statement in the buffer, sequentially.
  const handleRunScript = (scope: 'script-single' | 'script-tabs') =>
    submitBatch(splitSqlStatements(activeTab.sql), scope);

  // SPEC-036 / SPEC-041 FR-003: re-open loads the entry's SQL into the active
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

  // SPEC-041 FR-008: open a tab through the cap guard; at the cap show the dialog.
  const handleNewTab = () => {
    const id = tabs.openTab();
    if (id === null) setLimitOpen(true);
    else editorRef.current?.focus();
  };

  const requestClose = (id: string) => {
    const tab = tabs.tabs.find((t) => t.id === id);
    if (!tab) return;
    if (tab.sql.trim()) {
      setClosing(tab); // non-empty → confirm first (FR-005)
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

  // FR-008: derive the target database from the view body before opening the
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

  // SPEC-043 FR-001/002/003: resolve the name prompt into an upsert. targetId is
  // the saved query to write into (an existing id) or null to create a new one;
  // either way the active tab is (re)linked + relabelled and its dirty marker
  // clears (the saved sql now matches the tab sql).
  const handleSaveConfirm = ({name, targetId}: {name: string; targetId: string | null}) => {
    const now = new Date().toISOString();
    const existing = targetId ? savedById.get(targetId) : undefined;
    const query: SavedQuery = {
      id: targetId ?? crypto.randomUUID(),
      name,
      sql: activeTab.sql,
      // SPEC-077 FR-006: informational only (there's no active database). The
      // personal database is recorded as the fixed default context.
      database: username,
      createdAt: existing?.createdAt ?? now,
      updatedAt: now
    };
    saved.upsert(query).catch((e) => logBackgroundFailure('saved-queries', e));
    tabs.setActiveTabMeta({label: name, savedQueryId: query.id});
    setSaveOpen(false);
    editorRef.current?.focus();
  };

  // FR-006: open a saved query into a new linked tab (cap dialog honored).
  const handleOpenSaved = (q: SavedQuery) => {
    const id = tabs.openTab({label: q.name, sql: q.sql, savedQueryId: q.id});
    if (id === null) {
      setLimitOpen(true);
      return;
    }
    setSavedOpen(false);
    editorRef.current?.focus();
  };

  // FR-007: delete a saved query (JSON rewrite, never an S3 delete) and unlink any
  // open tab pointing at it (the tab keeps its SQL; a later Save creates new).
  const handleDeleteSaved = (id: string) => {
    saved.remove(id).catch((e) => logBackgroundFailure('saved-queries', e));
    tabs.unlinkSavedQuery(id);
  };

  // SPEC-044/077/100: the per-table rail actions, and the mobile nav-rail copy
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

  // SPEC-048/077: turn the active tab's SQL into a named view, in the background
  // (the editor keeps showing the user's SELECT). The target database is derived
  // from the view body's fully-qualified base tables (FR-008), captured in
  // `createViewDb` when the dialog opened.
  const handleCreateView = (name: string) => {
    const database = createViewDb;
    if (!database) return;
    const body = stripTrailingSemicolons(activeTab.sql);
    ddl.run({
      sql: `CREATE OR REPLACE VIEW ${database}.${name} AS ${body}`,
      database,
      describe: {success: `Created view ${name}`, failure: `Couldn\u2019t create view ${name}.`},
      onSettled: () => setCreateViewOpen(false)
    });
  };

  // SPEC-044 FR-005: drop the rail's table or view, recorded in history like any
  // other statement.
  const handleDropConfirm = () => {
    if (!dropping) return;
    const {database, table} = dropping;
    const isView = table.tableType === 'VIRTUAL_VIEW';
    ddl.run({
      sql: `DROP ${isView ? 'VIEW' : 'TABLE'} ${database}.${table.name}`,
      database,
      describe: {success: `Dropped ${table.name}`, failure: `Couldn\u2019t drop ${table.name}.`},
      onSettled: () => setDropping(null)
    });
  };

  // SPEC-078 FR-004: a batch failure names the failing statement's position and
  // makes clear the remaining statements did not run.
  const batchFailureMessage = (() => {
    const run = activeRun;
    if (!run?.failure) return null;
    const total = run.statements.length;
    if (total === 1) return run.failure.reason;
    const at = run.failure.statementIndex + 1;
    const skipped = total - at;
    const skippedNote =
      skipped === 0
        ? ''
        : skipped === 1
          ? ` Statement ${total} did not run.`
          : ` Statements ${at + 1}–${total} did not run.`;
    return `Statement ${at} of ${total} failed. ${run.failure.reason}${skippedNote}`;
  })();
  const errorMessage =
    runErrors[activeTabId] ??
    batchFailureMessage ??
    (activeStatus?.state === 'FAILED'
      ? toUserText({code: activeStatus.state, message: activeStatus.stateChangeReason})
      : null);
  const showError = !!errorMessage && !dismissed[activeTabId];
  const canRun = !!activeTab.sql.trim() && !activeIsInFlight;
  const canClear = activeTab.sql.length > 0 && !activeIsInFlight;
  const canSave = !!activeTab.sql.trim(); // FR-001: disabled only when empty

  // SPEC-049: Save results is offered only for a SUCCEEDED, row-returning result
  // (a result object with columns) — not a DDL / no-result statement. SPEC-078:
  // it saves the displayed result tab's execution.
  const canSaveResults = displayExecutionId !== null && !!displayOutputLocation && results.columns.length > 0;

  return (
    // Cap the workspace to the viewport (minus the h-14 header) so the results
    // pane scrolls internally instead of growing the page (feedback 2026-06-30).
    // Bounding the height here + `min-h-0` down the flex chain is what lets the
    // `overflow-auto` results region actually scroll; the schema rail already
    // scrolls itself (`overflow-y-auto`).
    <div className="flex h-[calc(100dvh-3.5rem)] min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* SPEC-100 FR-005: on a phone the rail lives in the nav drawer instead. */}
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
              savedQueries={saved.queries}
              savedLoading={saved.isLoading}
              savedError={saved.error}
              history={history}
              historyLoading={historyLoading}
              historyError={historyError}
              onRun={mobile.runSql}
              onView={mobile.viewSql}
              runDisabled={activeIsInFlight || mobile.pending}
            />
          ) : (
            <QueryResultsMobile
              title={mobileView.title}
              sql={mobileView.sql}
              onBack={mobile.back}
              onRun={() => mobile.runSql(mobileView.sql, mobileView.title)}
              runDisabled={activeIsInFlight || mobile.pending}
              status={mobile.ownsRun ? activeStatus : undefined}
              isInFlight={mobile.pending || (mobile.ownsRun && activeIsInFlight)}
              startedAt={mobile.ownsRun ? (activeRun?.startedAt ?? null) : null}
              hasResultSet={mobile.ownsRun && hasResultSet}
              totalRowCount={mobile.ownsRun ? rowCount.total : null}
              hasRun={mobile.ownsRun || mobile.pending}
              errorMessage={
                mobile.failedToStart ? (mobile.run?.error ?? null) : mobile.ownsRun && showError ? errorMessage : null
              }
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
                preset={layout.preset}
                onPresetChange={handleLayoutChange}
                isInFlight={activeIsInFlight}
                canRun={canRun}
                canClear={canClear}
                canSave={canSave}
                onClear={() => setClearOpen(true)}
                onSave={() => setSaveOpen(true)}
                onCreateView={handleOpenCreateView}
                onStop={handleStop}
                onRunStatement={handleRunStatement}
                onRunScript={handleRunScript}
              />

              {/* SPEC-079: the measured editor+results column. The editor pane takes
              the preset's clamped height; everything below it (status bar +
              results) flexes into the remainder and keeps scrolling internally. */}
              <div
                ref={layoutColumnRef}
                className="flex min-h-0 min-w-0 flex-1 flex-col">
                <div
                  className={cx(
                    'flex-none border-b border-border',
                    animateSplit && 'transition-[height] duration-200 ease-out motion-reduce:transition-none'
                  )}
                  style={{height: layout.editorHeight}}
                  onTransitionEnd={(e) => {
                    if (e.target === e.currentTarget && e.propertyName === 'height') setAnimateSplit(false);
                  }}>
                  <Suspense
                    fallback={
                      <div className="flex h-full items-center justify-center bg-surface-2 text-sm text-text-3">
                        Loading editor&hellip;
                      </div>
                    }>
                    <SqlEditor
                      ref={editorRef}
                      value={activeTab.sql}
                      onChange={tabs.setActiveSql}
                      onRun={handleRunStatement}
                      onRunScriptSingle={() => handleRunScript('script-single')}
                      onRunScriptTabs={() => handleRunScript('script-tabs')}
                      completionSchemas={completionSchemas}
                    />
                  </Suspense>
                </div>

                <QueryResultsRegion
                  run={activeRun}
                  status={activeStatus}
                  isInFlight={activeIsInFlight}
                  batchDone={activeBatchDone}
                  editorOwnsRun={editorOwnsRun}
                  editorExecutionId={editorExecutionId}
                  editorDisplayExecutionId={editorDisplayExecutionId}
                  displayExecutionId={displayExecutionId}
                  hasResultSet={hasResultSet}
                  totalRowCount={rowCount.total}
                  results={results}
                  pageSize={resultsPageSize}
                  colWidths={colWidths}
                  showResultTabs={showResultTabs}
                  showError={showError}
                  errorMessage={errorMessage}
                  onDismissError={() => dismissError(activeTabId)}
                  onSelectResultTab={(index) => selectResultTab(activeTabId, index)}
                  canSaveResults={canSaveResults}
                  onSaveResults={saveResults.openDialog}
                />
              </div>
            </div>
          </>
        )}
      </main>

      {/* Editor-shell drawers: opened from the tab strip, and their actions
          (Open / Re-run) load SQL into the editor — so they belong to the
          editor's breakpoints only. The mobile home is the surface for these
          two lists below `tablet` (SPEC-100). */}
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
            queries={saved.queries}
            isLoading={saved.isLoading}
            error={saved.error}
            onOpen={handleOpenSaved}
            onDelete={handleDeleteSaved}
          />
        </>
      )}

      <QueryDialogs
        clear={{open: clearOpen, onConfirm: handleClearConfirm, onCancel: () => setClearOpen(false)}}
        save={{
          open: saveOpen,
          initialName: activeLinkedSaved?.name ?? '',
          savedQueries: saved.queries,
          linkedId: activeTab.savedQueryId,
          onSave: handleSaveConfirm,
          onCancel: () => setSaveOpen(false)
        }}
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
