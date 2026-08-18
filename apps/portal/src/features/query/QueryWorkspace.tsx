import {Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {useLocation, useSearchParams} from 'react-router';
import {useAuth} from '../auth';
import {cx} from '../../lib/cx';
import {useQueryResults} from '../catalog/useQueryResults';
import {useResultsPageSize} from './useResultsPageSize';
import {useResultRowCount} from '../catalog/useResultRowCount';
import {useColumnWidths} from '../catalog/useColumnWidths';
import {useQueryHistory} from './useQueryHistory';
import {useQueryTabs} from './useQueryTabs';
import {useTabRuns} from './useTabRuns';
import {useRunDdl} from './useRunDdl';
import {useMobileQuerySurface} from './useMobileQuerySurface';
import {useSaveResults} from '../catalog/useSaveResults';
import {useTableActions} from './useTableActions';
import {useEditorLayout} from './useEditorLayout';
import {useSavedQueries} from '../saved-queries/useSavedQueries';
import {useSavedQuerySpace} from '../saved-queries/useSavedQuerySpace';
import {useQuerySpaces} from '../catalog/useQuerySpaces';
import {ensureSavedQueriesFolder, readSavedQuery} from '../saved-queries/savedQueries.service';
import {useSaveQuery} from '../saved-queries/useSaveQuery';
import {useConnections} from '../connections/useConnections';
import {useFeature} from '../feature-flags';
import {useAllSchemas, useSchema} from '../catalog/useSchema';
import {
  deriveViewTargetDatabase,
  resolveRunStatements,
  sameSql,
  splitSqlStatements,
  stripTrailingSemicolons
} from './query.sql';
import {QUERY_TABS_MAX} from './query.constants';
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
import type {QueryHistoryEntry, QueryTab} from './query.types';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {QuerySpace, GlueTableSummary} from '../catalog/catalog.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it.
const SqlEditor = lazy(() => import('./SqlEditor').then((m) => ({default: m.SqlEditor})));

// The query workspace: schema browser (left) + editor/status/results
// (main), wired to the catalog data layer. The editor is multi-tab:
// each tab is an independent query window with its own SQL + run state; Run/Clear/
// Stop/status/results all act on the active tab.
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

  // The editor/results layout preset. The editor+results column is
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
  // "Refresh table" dialog + enqueue state, wired the same way. The hook
  // also owns the rail invalidation, since the enqueue is the only signal there is.
  // `/query?refreshTable={db}.{table}&removed={names}` — the link
  // `columns_removed` notification carries. Read from the RAW query string
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
  // existence oracle, and the rail is the authority on what exists.
  const linkDatabase =
    link && !connectionsLoading && connections.some((c) => c.database === link.database && isConnectionUsable(c))
      ? link.database
      : null;
  const {data: linkSchema} = useSchema(linkDatabase);
  const linkTarget = useMemo(() => {
    if (!link || !linkSchema) return null;
    // A view has no folder to re-read and a table with no location can't be turned
    // into a request (the menu item is disabled for the same reason), so a link
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
  // Create view. The target database is derived from the body.
  const [createViewOpen, setCreateViewOpen] = useState(false);
  const [createViewDb, setCreateViewDb] = useState('');
  const editorRef = useRef<SqlEditorHandle>(null);
  // The list fields feed the mobile browse-first home; the
  // desktop drawer subscribes to the same cache key, so this adds no fetch.
  const {
    history,
    isLoading: historyLoading,
    error: historyError,
    appendEntry,
    updateEntry
  } = useQueryHistory(username || null);
  // Saved queries are `.sql` files in a SPACE's `saved_queries/`
  // folder. WHICH space is one piece of state, shared by loading and
  // saving — the personal space plus every active shared space, and the memory a
  // successful save updates.
  const allSpaces = useQuerySpaces();
  const personalSpace: QuerySpace | null = allSpaces[0] ?? null;
  // Gated at the VIEW, exactly as the connections list above is: with shared
  // workspaces hidden, offering a colleague's space in the selector would name spaces the
  // rest of the app has just stopped showing. `useQuerySpaces` still resolves them —
  // a flag may not touch a service — and a remembered shared space
  // falls through `useSavedQuerySpace`'s existing "not in the list" path to personal.
  const savedSpaces = useMemo(
    () => (sharedSpacesEnabled ? allSpaces : allSpaces.slice(0, 1)),
    [sharedSpacesEnabled, allSpaces]
  );
  const savedSpace = useSavedQuerySpace(username || null, savedSpaces);
  const saved = useSavedQueries(savedSpace.space);

  // Hold the folder open, once per space per session. Best effort — a failure is
  // logged and the workspace renders regardless, because saving a query creates the
  // prefix on its own.
  //
  // The `.catch` is what makes "best effort" true of a REJECTION and not just of a failed
  // `ServiceResult`. The service does not throw by contract, but a `.then`-only chain
  // turns any breach of that contract into an unhandled rejection, which fails the whole
  // test run rather than this one non-blocking call.
  useEffect(() => {
    if (!personalSpace) return;
    void ensureSavedQueriesFolder(personalSpace)
      .then((result) => {
        if (!result.success) logBackgroundFailure('saved-queries-folder', result.error);
      })
      .catch((error: unknown) => logBackgroundFailure('saved-queries-folder', error));
  }, [personalSpace]);

  // a linked tab is "dirty" when its editor SQL differs from the file
  // it was opened from. A `.sql` object carries no body until it is READ, so the
  // comparison is against what this session last saw — the body fetched on open, or the
  // buffer written on save — rather than a `sql` field on a list row that no longer
  // exists. A tab restored from `sessionStorage` after a reload has no snapshot and
  // shows no marker until it is opened or saved again; the alternative was a GetObject
  // per linked tab on every mount.
  const [savedSnapshots, setSavedSnapshots] = useState<ReadonlyMap<string, string>>(() => new Map());
  const rememberSavedSql = useCallback(
    (key: string, sql: string) => setSavedSnapshots((prev) => new Map(prev).set(key, sql)),
    []
  );
  const dirtyTabIds = useMemo(
    () =>
      new Set(
        tabs.tabs
          .filter((tab) => {
            const snapshot = tab.savedQuery ? savedSnapshots.get(tab.savedQuery.key) : undefined;
            return snapshot !== undefined && !sameSql(snapshot, tab.sql);
          })
          .map((tab) => tab.id)
      ),
    [tabs.tabs, savedSnapshots]
  );
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
    selectResultTab
  } = useTabRuns({username, activeTabId, tabs: tabs.tabs, appendEntry, updateEntry});

  // Create view and Drop table were the same forty lines twice.
  // One background-DDL path now runs, records and reports both.
  const ddl = useRunDdl({username, appendEntry, toast});

  // The below-`tablet` browse-first surface — its view state, the
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
  const displayOutputLocation = displayedResultTab?.outputLocation ?? activeStatus?.outputLocation;

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
  // one page at a time via the pager, sized by the workspace-global
  // "Rows per page" value — one shared value for every result tab.
  const resultsPageSize = useResultsPageSize(username || null);
  const results = useQueryResults(displayExecutionId, resultsPageSize.pageSize);

  // Exact total row count via a background page-walk. Gated on a result
  // set actually existing (columns present) so DDL/no-result statements show no
  // row-count stat; scoped to the execution id so a new run / tab switch recomputes.
  const hasResultSet = displayExecutionId !== null && results.columns.length > 0;
  const rowCount = useResultRowCount(hasResultSet ? displayExecutionId : null);

  // Result-column widths, keyed by execution id. Lives here (not in
  // QueryResultsTable, which unmounts when the active tab has no results) so a
  // user's resizes survive Prev/Next AND query/result-tab switches; a new query
  // (new execution id) starts from defaults.
  const colWidths = useColumnWidths(displayExecutionId, results.columns.length);

  // Run Statement — the selection, else the statement under the
  // cursor, else the sole statement. When the editor handle isn't available
  // (still lazy-loading), the cursor defaults to the buffer end (last statement).
  const handleRunStatement = () => {
    const buffer = activeTab.sql;
    const statements = splitSqlStatements(buffer);
    const selection = editorRef.current?.getSelectionRange() ?? null;
    const cursor = editorRef.current?.getCursorOffset() ?? buffer.length;
    submitBatch(resolveRunStatements(buffer, statements, selection, cursor), 'statement');
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

  // Every save asks — for a name AND a destination, a linked
  // tab's included, pre-filled and selected — because a user about to overwrite a file
  // should be told which file, in which space, before it happens. The whole path (the
  // validation, the folder marker, the write, the `Collision` round-trip and the toast)
  // lives in the hook; the workspace supplies the destinations and takes the result.
  const saveQuery = useSaveQuery({
    spaces: savedSpaces,
    defaultSpace: savedSpace.space,
    // The hook takes the two fields it reads, not the tab that happens to
    // carry them — the Data Explorer has no `QueryTab` to hand it.
    payload: {sql: activeTab.sql, link: activeTab.savedQuery},
    toast,
    onSaved: (query, sql) => {
      // The buffer just written IS the file's content, so the dirty marker clears
      // without a read-back.
      rememberSavedSql(query.key, sql);
      tabs.setActiveTabMeta({
        label: query.name,
        savedQuery: {spaceId: query.spaceId, bucket: query.bucket, key: query.key, name: query.name}
      });
      // ONE memory of "the space I am working in" — the next save and the next
      // load both open where the user last was, rather than two memories that disagree.
      savedSpace.selectSpace(query.spaceId);
      saved.refresh();
      editorRef.current?.focus();
    }
  });

  // Open a saved query into a new linked tab (cap dialog honored). Exactly one
  // GetObject, and only here — a list row never fetches a body.
  const handleOpenSaved = (query: SavedQuery) => {
    // The cap is checked BEFORE the fetch. Reading a body only to
    // discard it and raise the limit dialog spends a GetObject on a tab that was never
    // going to open.
    if (tabs.tabs.length >= QUERY_TABS_MAX) {
      setLimitOpen(true);
      return;
    }
    void (async () => {
      const body = await readSavedQuery({bucket: query.bucket, key: query.key});
      if (!body.success) {
        // The drawer stays open and no tab is opened: the user asked for this file, and
        // an empty tab labelled with its name would be a worse answer than the message.
        toast.push({variant: 'danger', message: toUserText(body.error)});
        return;
      }
      const id = tabs.openTab({
        // The label is the FILE's name from the store's own function, so a tab and a
        // list row can never disagree about what a file is called.
        label: query.name,
        sql: body.data,
        savedQuery: {spaceId: query.spaceId, bucket: query.bucket, key: query.key, name: query.name}
      });
      if (id === null) {
        setLimitOpen(true);
        return;
      }
      rememberSavedSql(query.key, body.data);
      setSavedOpen(false);
      editorRef.current?.focus();
    })();
  };

  // The mobile Saved list has no SQL to hand its Run/View
  // until the file is read, so the fetch happens here — one GetObject, on the card the
  // user actually chose, and never merely because the list is on screen.
  const withSavedSql = (query: SavedQuery, use: (sql: string, title: string) => void) => {
    void (async () => {
      const body = await readSavedQuery({bucket: query.bucket, key: query.key});
      if (!body.success) {
        toast.push({variant: 'danger', message: toUserText(body.error)});
        return;
      }
      use(body.data, query.name);
    })();
  };

  // Delete the file and unlink any open tab pointing at it (the tab keeps its
  // SQL; a later Save creates a new file).
  const handleDeleteSaved = (query: SavedQuery) => {
    saved.remove(query).catch((e) => {
      toast.push({variant: 'danger', message: `Couldn’t delete the query. ${toUserText(e)}`});
    });
    tabs.unlinkSavedQuery(query.key);
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
    const body = stripTrailingSemicolons(activeTab.sql);
    ddl.run({
      sql: `CREATE OR REPLACE VIEW ${database}.${name} AS ${body}`,
      database,
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
      sql: `DROP ${isView ? 'VIEW' : 'TABLE'} ${database}.${table.name}`,
      database,
      describe: {success: `Dropped ${table.name}`, failure: `Couldn\u2019t drop ${table.name}.`},
      onSettled: () => setDropping(null)
    });
  };

  // a batch failure names the failing statement's position and
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
  const canSave = !!activeTab.sql.trim(); // disabled only when empty

  // Save results is offered only for a SUCCEEDED, row-returning result
  // (a result object with columns) — not a DDL / no-result statement.
  // it saves the displayed result tab's execution.
  const canSaveResults = displayExecutionId !== null && !!displayOutputLocation && results.columns.length > 0;

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
              onDeleteSaved={handleDeleteSaved}
              history={history}
              historyLoading={historyLoading}
              historyError={historyError}
              onRun={mobile.runSql}
              onView={mobile.viewSql}
              onRunSaved={(q) => withSavedSql(q, mobile.runSql)}
              onViewSaved={(q) => withSavedSql(q, mobile.viewSql)}
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
                onSave={saveQuery.openDialog}
                onCreateView={handleOpenCreateView}
                onStop={handleStop}
                onRunStatement={handleRunStatement}
                onRunScript={handleRunScript}
              />

              {/* the measured editor+results column. The editor pane takes
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
            onOpen={handleOpenSaved}
            onDelete={handleDeleteSaved}
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
