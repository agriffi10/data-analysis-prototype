import {Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {useLocation, useNavigate, useSearchParams} from 'react-router';
import {useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {Button} from '../../components/Button';
import {Menu} from '../../components/Menu';
import {Banner} from '../../components/Banner';
import {cx} from '../../lib/cx';
import {EyeIcon, PlayIcon, SaveIcon, TrashLidIcon} from '../../components/icons';
import {getTableDdl} from './query.service';
import {copyObject} from '../file-browser/fileBrowser.service';
import {invalidateListing} from '../../lib/queryClient';
import {parseS3Url} from '../../lib/s3Url';
import {spaceBuckets} from '../../lib/userSpace';
import {useQueryResults} from './useQueryResults';
import {useResultsPageSize} from './useResultsPageSize';
import {ResultsPageSizeControl} from './ResultsPageSizeControl';
import {useResultRowCount} from './useResultRowCount';
import {useColumnWidths} from './useColumnWidths';
import {useQueryHistory} from './useQueryHistory';
import {useQueryTabs} from './useQueryTabs';
import {useTabRuns} from './useTabRuns';
import {useRunDdl} from './useRunDdl';
import {useEditorLayout} from './useEditorLayout';
import {EditorLayoutControl} from './EditorLayoutControl';
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
import {ResultTabs} from './ResultTabs';
import {SchemaBrowser, SchemaTree, type TableActions} from './SchemaBrowser';
import {QueryMobileView} from './QueryMobileView';
import {QueryResultsMobile} from './QueryResultsMobile';
import {useIsMobile} from '../../lib/useBreakpoint';
import {useProvideNavRail} from '../../components/navRailContext';
import {TableShareDialog, useTableShare} from '../table-share';
import {RefreshTableDialog, parseRefreshLink, useTableRefresh} from '../table-builder';
import {DropTableDialog} from './DropTableDialog';
import {CreateViewDialog} from './CreateViewDialog';
import {SaveResultsDialog, type DestinationSpace} from './SaveResultsDialog';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {useToast} from '../../components/toastContext';
import {logBackgroundFailure, toUserText} from '../../lib/errorMessages';
import {QueryStatusBar} from './QueryStatusBar';
import {QueryResultsTable} from './QueryResultsTable';
import {QueryHistoryPanel} from './QueryHistoryPanel';
import {SavedQueriesPanel} from './SavedQueriesPanel';
import {QueryTabStrip} from './QueryTabStrip';
import {ClearQueryDialog} from './ClearQueryDialog';
import {CloseTabDialog} from './CloseTabDialog';
import {TabLimitDialog} from './TabLimitDialog';
import {SaveQueryDialog} from './SaveQueryDialog';
import type {SqlEditorHandle} from './SqlEditor';
import {isConnectionUsable} from '../connections/connection.types';
import type {
  MobileHomeTab,
  MobileQueryView,
  QueryHistoryEntry,
  QueryTab,
  SavedQuery,
  GlueTableSummary
} from './query.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it (SPEC-035 FR-003).
const SqlEditor = lazy(() => import('./SqlEditor').then((m) => ({default: m.SqlEditor})));

// SPEC-100 FR-003: the editor toolbar is icon-only in the tablet band so its
// actions fit the narrower main column; each button keeps its `aria-label`.
const TOOLBAR_LABEL = 'hidden desktop:inline';

// SPEC-035 query workspace (FR-002): schema browser (left) + editor/status/results
// (main), wired to the SPEC-034 data layer. SPEC-041 makes the editor multi-tab:
// each tab is an independent query window with its own SQL + run state; Run/Clear/
// Stop/status/results all act on the active tab.
export function QueryWorkspace() {
  const {user} = useAuth();
  const username = user?.username ?? '';
  const queryClient = useQueryClient();
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

  // SPEC-055 FR-003: the spaces a result can be saved into — the user's own space
  // first, then every shared space they currently belong to (usable). The picker
  // excludes each space's protected `athenaresults/` folder.
  const saveSpaces = useMemo<DestinationSpace[]>(() => {
    if (!userSpaceBucket) return [];
    const personal: DestinationSpace = {
      id: 'personal',
      label: 'My files',
      bucket: userSpaceBucket,
      rootPrefix: `${username}/`,
      rootLabel: 'My Files'
    };
    const shared: DestinationSpace[] = sharedSpaceBucket
      ? connections
          .filter((c) => c.kind === 'shared' && isConnectionUsable(c))
          .map((c) => ({
            id: c.database,
            label: c.database,
            bucket: sharedSpaceBucket,
            rootPrefix: `${c.database}/`,
            rootLabel: c.database
          }))
      : [];
    return [personal, ...shared];
  }, [userSpaceBucket, sharedSpaceBucket, username, connections]);

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

  const [mobileView, setMobileView] = useState<MobileQueryView>({kind: 'home'});
  const [mobileHomeTab, setMobileHomeTab] = useState<MobileHomeTab>('saved');
  // What the mobile results view submitted, and where. The view adopts a tab's
  // status/results ONLY while this token is the installed run's — SQL text is not
  // a run identity (the same text can name an older execution), and a submit is
  // not installed synchronously, so an ungated view shows a previous query's
  // outcome under the current query's title. `phase` is reported by the submit
  // itself rather than inferred.
  const mobileRunTokenRef = useRef(0);
  const [mobileRun, setMobileRun] = useState<{
    token: number;
    tabId: string;
    phase: 'submitting' | 'started' | 'failed';
    /** Failure text for a submit that never started — owned here, not by the tab. */
    error?: string;
  } | null>(null);

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
  // SPEC-049: Save results.
  const [saveResultsOpen, setSaveResultsOpen] = useState(false);
  const [saveInFlight, setSaveInFlight] = useState(false);
  // A pending overwrite confirm when the chosen destination key already exists.
  // SPEC-055: carries source + dest buckets so the retry repeats the same
  // (possibly cross-bucket) copy.
  const [overwritePrompt, setOverwritePrompt] = useState<{
    sourceBucket: string;
    sourceKey: string;
    destBucket: string;
    destPrefix: string;
    filename: string;
  } | null>(null);

  const navigate = useNavigate();
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

  // SPEC-049: copy the query's complete Athena result object into the user's space.
  // A server-side CopyObject of `{username}/athenaresults/{id}.csv` captures ALL
  // rows, independent of how many pages the results table loaded. The destination
  // listing is invalidated so the new file appears if the user browses there, and a
  // success toast offers a "View in Files" deep-link (SPEC-044).
  const doSaveCopy = (args: {
    sourceBucket: string;
    sourceKey: string;
    destBucket: string;
    destPrefix: string;
    filename: string;
    overwrite: boolean;
  }) => {
    const destKey = `${args.destPrefix}${args.filename}`;
    setSaveInFlight(true);
    void (async () => {
      const result = await copyObject({
        bucket: args.sourceBucket,
        destBucket: args.destBucket,
        sourceKey: args.sourceKey,
        destKey,
        username,
        overwrite: args.overwrite
      });
      setSaveInFlight(false);
      if (!result.success) {
        // A destination collision returns to a warn-and-confirm (SPEC-039).
        if (result.error.code === 'Collision') {
          setSaveResultsOpen(false);
          setOverwritePrompt({
            sourceBucket: args.sourceBucket,
            sourceKey: args.sourceKey,
            destBucket: args.destBucket,
            destPrefix: args.destPrefix,
            filename: args.filename
          });
          return;
        }
        toast.push({
          variant: 'danger',
          message: `Couldn’t save results. ${toUserText(result.error)}`
        });
        return;
      }
      setSaveResultsOpen(false);
      setOverwritePrompt(null);
      void invalidateListing(queryClient, args.destBucket, args.destPrefix);
      // SPEC-055: the Files browser only renders the personal space until SPEC-057,
      // so the "View in Files" deep-link is offered only for a personal-space save.
      const isPersonalDest = args.destBucket === userSpaceBucket;
      toast.push({
        variant: 'success',
        message: `Saved to ${args.destPrefix}${args.filename}`,
        ...(isPersonalDest && {
          action: {
            label: 'View in Files',
            onClick: () => {
              toast.dismiss();
              navigate(`/files?prefix=${encodeURIComponent(args.destPrefix)}`);
            }
          }
        })
      });
    })();
  };

  const handleSaveResults = (args: {destBucket: string; destPrefix: string; filename: string}) => {
    // SPEC-078: save the DISPLAYED result (the active result tab's execution),
    // not necessarily the batch's last statement.
    const outputLocation = displayOutputLocation;
    if (!outputLocation) return;
    const parsed = parseS3Url(outputLocation);
    if (!parsed) {
      toast.push({
        variant: 'danger',
        message: 'Couldn’t read the query result location.'
      });
      return;
    }
    doSaveCopy({...args, sourceBucket: parsed.bucket, sourceKey: parsed.key, overwrite: false});
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

  // ── SPEC-044 table actions ──────────────────────────────────────────────
  // Derive the in-space S3 key (folder) backing a table from its Glue LOCATION;
  // null when missing or outside the user's own prefix (FR-002 guard).
  const tablePrefix = (table: GlueTableSummary): string | null => {
    const parsed = parseS3Url(table.location);
    if (!parsed) return null;
    const key = parsed.key.endsWith('/') ? parsed.key : `${parsed.key}/`;
    return username && key.startsWith(`${username}/`) ? key : null;
  };

  // SPEC-077 FR-007: each per-table action takes the database from the rail node
  // the table was invoked from (a table under `db_a` acts on `db_a.<table>`) —
  // there is no active-database selection to source it from.
  const tableActions = {
    canViewSourceFiles: (table: GlueTableSummary) => tablePrefix(table) !== null,
    // Deep-link the file browser to the table's data folder (location-based; no db).
    onViewSourceFiles: (_database: string, table: GlueTableSummary) => {
      const key = tablePrefix(table);
      if (!key) return;
      navigate(`/files?prefix=${encodeURIComponent(key)}`);
    },
    // SHOW CREATE TABLE against the node's database → a new, non-run "DDL: {table}" tab.
    onViewDdl: (database: string, table: GlueTableSummary) => {
      toast.push({variant: 'info', message: `Loading DDL for ${table.name}…`});
      void (async () => {
        const result = await getTableDdl({
          database,
          table: table.name,
          username,
          isView: table.tableType === 'VIRTUAL_VIEW'
        });
        if (!result.success) {
          toast.push({
            variant: 'danger',
            message: `Couldn’t load DDL for ${table.name}. ${toUserText(result.error)}`
          });
          return;
        }
        toast.dismiss();
        // SPEC-100: the drawer puts these actions on a phone too, where there is
        // no editor to open a tab into — show the DDL in the read-only view.
        if (isMobile) {
          handleMobileView(result.data, `DDL: ${table.name}`);
          return;
        }
        const id = tabs.openTab({
          label: `DDL: ${table.name}`,
          sql: result.data
        });
        if (id === null) setLimitOpen(true);
        else editorRef.current?.focus();
      })();
    },
    // Open a "{table}" tab pre-filled with an unbounded, fully-qualified SELECT *
    // + auto-run — the results pager (at the user's page size) walks the whole
    // table; the workgroup bytes-scanned cutoff is the cost guard (SPEC-105).
    onViewData: (database: string, table: GlueTableSummary) => {
      const sql = `SELECT * FROM ${database}.${table.name}`;
      // SPEC-100: on a phone the run goes to the mobile results view; opening a
      // tab there would run a query with nothing able to display it.
      if (isMobile) {
        handleMobileRun(sql, table.name);
        return;
      }
      const id = tabs.openTab({label: table.name, sql});
      if (id === null) {
        setLimitOpen(true);
        return;
      }
      editorRef.current?.focus();
      submitBatch(splitSqlStatements(sql), 'script-single', id); // auto-run into the just-opened tab
    },
    // SPEC-145: open the Refresh dialog for this rail table. Unlike Share, `open`
    // takes the whole summary — the request's space is derived from the table's own
    // `location`, the only thing in the workspace that knows where its files live.
    onRefreshTable: (database: string, table: GlueTableSummary) => refresh.open(database, table),
    // SPEC-093: open the Share dialog for this rail table (base tables only — the
    // menu omits the item for views); submission + toasts live in useTableShare.
    onShareTable: (database: string, table: GlueTableSummary) => share.open(database, table.name),
    // Confirm, then drop in the background (handled on confirm) — carries the node's db.
    onDropTable: (database: string, table: GlueTableSummary) => setDropping({database, table})
  };

  // SPEC-100 FR-005: below `tablet` the inline rail is gone, so the same tree is
  // fed into the mobile AppNavDrawer's contextual slot. The registered node must
  // keep a stable identity (useProvideNavRail registers it in an effect), so the
  // drawer's copy delegates through a ref to the current handlers rather than
  // closing over the per-render `tableActions` object.
  const tableActionsRef = useRef(tableActions);
  useEffect(() => {
    tableActionsRef.current = tableActions;
  });
  const railActions = useMemo<TableActions>(
    () => ({
      canViewSourceFiles: (table) => tableActionsRef.current.canViewSourceFiles(table),
      onViewSourceFiles: (database, table) => tableActionsRef.current.onViewSourceFiles(database, table),
      onViewDdl: (database, table) => tableActionsRef.current.onViewDdl(database, table),
      onViewData: (database, table) => tableActionsRef.current.onViewData(database, table),
      onRefreshTable: (database, table) => tableActionsRef.current.onRefreshTable(database, table),
      onShareTable: (database, table) => tableActionsRef.current.onShareTable(database, table),
      onDropTable: (database, table) => tableActionsRef.current.onDropTable(database, table)
    }),
    []
  );
  const navRail = useMemo(
    () =>
      isMobile ? (
        <div className="p-3">
          <p className="px-3 pb-1 pt-1 text-xs font-semibold uppercase tracking-[.04em] text-text-3">Databases</p>
          <SchemaTree
            connections={connections}
            actions={railActions}
          />
        </div>
      ) : null,
    [isMobile, connections, railActions]
  );
  useProvideNavRail(navRail);

  // SPEC-100 FR-004/006: run a saved/history entry from the mobile home through
  // the SAME run path the editor uses, then show the results view; View opens it
  // read-only without running.
  // The tab's SQL is deliberately NOT set here: submitBatch takes the statements
  // explicitly, and writing the editor buffer would overwrite (and persist over)
  // a draft the user left on a wider screen.
  const handleMobileRun = (sql: string, title: string) => {
    const token = mobileRunTokenRef.current + 1;
    const tabId = activeTabId;
    // Navigate only if the submit is actually accepted, so a refused tap never
    // strands the user on a page for a query that isn't running.
    const started = submitBatch(splitSqlStatements(sql), 'script-single', tabId, {
      token,
      onOutcome: (ok, error) =>
        setMobileRun((cur) => (cur?.token === token ? {...cur, phase: ok ? 'started' : 'failed', error} : cur))
    });
    if (!started) return;
    mobileRunTokenRef.current = token;
    setMobileRun({token, tabId, phase: 'submitting'});
    setMobileView({kind: 'results', sql, title});
  };
  const handleMobileView = (sql: string, title: string) => {
    setMobileRun(null);
    setMobileView({kind: 'results', sql, title});
  };
  const handleMobileBack = () => {
    setMobileRun(null);
    setMobileView({kind: 'home'});
  };

  // Crossing up out of mobile hands the tab back to the editor, so the mobile
  // surface's run bookkeeping must not survive to be matched against a later,
  // unrelated desktop run. Render-phase state adjustment (the React "derive state
  // on change" pattern), as elsewhere in this feature — not an Effect.
  const [prevIsMobile, setPrevIsMobile] = useState(isMobile);
  if (isMobile !== prevIsMobile) {
    setPrevIsMobile(isMobile);
    if (!isMobile) {
      setMobileRun(null);
      setMobileView({kind: 'home'});
    }
  }

  // The view owns a run only while ITS submit is the one installed in the tab it
  // submitted into — the tab can change under the view, and a later run replaces
  // the entry. Pending and failed are recorded at submit time, never inferred
  // from "no run and no error": that residual turns into a permanent phantom
  // when the error is dismissed.
  const mobileRunTab = mobileRun ? runs[mobileRun.tabId] : undefined;
  const mobileOwnsRun =
    mobileRun !== null && mobileRun.tabId === activeTabId && mobileRunTab?.token === mobileRun.token;
  const mobileRunPending = mobileRun?.phase === 'submitting' && !mobileOwnsRun;
  const mobileRunFailedToStart = mobileRun?.phase === 'failed';

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

  // SPEC-049: default file name — the saved query's name when the tab is linked,
  // else a generic stamp; sanitized to the leaf-name rule (no slash/control chars).
  const savedResultsDefaultName = (() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, '0');
    const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
    const base = activeLinkedSaved?.name
      ? // eslint-disable-next-line no-control-regex
        activeLinkedSaved.name.replace(/[/\x00-\x1f]/g, '-').trim()
      : 'query-results';
    return `${base}-${stamp}`;
  })();

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
              tab={mobileHomeTab}
              onTabChange={setMobileHomeTab}
              savedQueries={saved.queries}
              savedLoading={saved.isLoading}
              savedError={saved.error}
              history={history}
              historyLoading={historyLoading}
              historyError={historyError}
              onRun={handleMobileRun}
              onView={handleMobileView}
              runDisabled={activeIsInFlight || mobileRunPending}
            />
          ) : (
            <QueryResultsMobile
              title={mobileView.title}
              sql={mobileView.sql}
              onBack={handleMobileBack}
              onRun={() => handleMobileRun(mobileView.sql, mobileView.title)}
              runDisabled={activeIsInFlight || mobileRunPending}
              status={mobileOwnsRun ? activeStatus : undefined}
              isInFlight={mobileRunPending || (mobileOwnsRun && activeIsInFlight)}
              startedAt={mobileOwnsRun ? (activeRun?.startedAt ?? null) : null}
              hasResultSet={mobileOwnsRun && hasResultSet}
              totalRowCount={mobileOwnsRun ? rowCount.total : null}
              hasRun={mobileOwnsRun || mobileRunPending}
              errorMessage={
                mobileRunFailedToStart ? (mobileRun?.error ?? null) : mobileOwnsRun && showError ? errorMessage : null
              }
              onDismissError={() => {
                // A submit that never started owns its error outright; anything
                // else is the tab's run reporting a failure.
                if (mobileRunFailedToStart) setMobileRun(null);
                else dismissError(activeTabId);
              }}
              results={results}
              displayExecutionId={mobileOwnsRun ? displayExecutionId : null}
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
              <div className="flex min-h-[52px] flex-none flex-wrap items-center gap-3 border-b border-border bg-surface px-5 py-2">
                <EditorLayoutControl
                  preset={layout.preset}
                  onChange={handleLayoutChange}
                />
                <div className="flex-1" />
                <Button
                  variant="ghost"
                  onClick={() => setClearOpen(true)}
                  disabled={!canClear}
                  aria-label="Clear query">
                  <TrashLidIcon />
                  <span className={TOOLBAR_LABEL}>Clear</span>
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => setSaveOpen(true)}
                  disabled={!canSave}
                  aria-label="Save query">
                  <SaveIcon />
                  <span className={TOOLBAR_LABEL}>Save</span>
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    // FR-008: derive the target database from the view body before
                    // opening the dialog; a non-derivable body raises a clear error
                    // and never silently picks a database.
                    const target = deriveViewTargetDatabase(stripTrailingSemicolons(activeTab.sql));
                    if ('error' in target) {
                      toast.push({variant: 'danger', message: target.error});
                      return;
                    }
                    setCreateViewDb(target.database);
                    setCreateViewOpen(true);
                  }}
                  disabled={!canSave}
                  aria-label="Create view">
                  <EyeIcon />
                  <span className={TOOLBAR_LABEL}>Create view</span>
                </Button>
                {activeIsInFlight ? (
                  <Button
                    variant="ghost"
                    onClick={handleStop}
                    aria-label="Stop the running query"
                    className="text-danger hover:bg-danger-soft hover:text-danger">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      className="h-4 w-4"
                      aria-hidden="true">
                      <rect
                        x="6"
                        y="6"
                        width="12"
                        height="12"
                        rx="2"
                      />
                    </svg>
                    <span className={TOOLBAR_LABEL}>Stop</span>
                  </Button>
                ) : (
                  // SPEC-078 FR-005: three distinct run scopes as a split button.
                  // Run Statement stays the primary action (⌘⏎); the two whole-script
                  // scopes — which differ only in how results are shown — live in an
                  // attached dropdown so the toolbar stays compact.
                  <div className="inline-flex items-stretch">
                    <Button
                      variant="primary"
                      onClick={handleRunStatement}
                      disabled={!canRun}
                      title="Run the selection or the statement under the cursor (⌘⏎)"
                      aria-label="Run statement"
                      className="rounded-r-none">
                      <PlayIcon />
                      <span className={TOOLBAR_LABEL}>Run Statement</span>
                    </Button>
                    <Menu
                      ariaLabel="More run options"
                      align="right"
                      trigger={({open, toggle, ref, menuId}) => (
                        <Button
                          ref={ref}
                          variant="primary"
                          onClick={toggle}
                          disabled={!canRun}
                          aria-haspopup="menu"
                          aria-expanded={open}
                          aria-controls={open ? menuId : undefined}
                          aria-label="More run options"
                          title="More run options"
                          className="rounded-l-none border-l border-white/25 px-2">
                          <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            className={cx('h-4 w-4 transition-transform', open && 'rotate-180')}
                            aria-hidden="true">
                            <path d="M6 9l6 6 6-6" />
                          </svg>
                        </Button>
                      )}
                      items={[
                        {
                          kind: 'action',
                          label: 'Run Query Tab',
                          icon: (
                            <svg
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              className="h-4 w-4"
                              aria-hidden="true">
                              <path d="M5 4l8 8-8 8" />
                              <path d="M14 20h6" />
                            </svg>
                          ),
                          onSelect: () => handleRunScript('script-single')
                        },
                        {
                          kind: 'action',
                          label: 'Run Multiple Queries',
                          icon: (
                            <svg
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              className="h-4 w-4"
                              aria-hidden="true">
                              <path d="M4 4l6 8-6 8" />
                              <rect
                                x="13"
                                y="5"
                                width="7"
                                height="5"
                                rx="1"
                              />
                              <rect
                                x="13"
                                y="14"
                                width="7"
                                height="5"
                                rx="1"
                              />
                            </svg>
                          ),
                          onSelect: () => handleRunScript('script-tabs')
                        }
                      ]}
                    />
                  </div>
                )}
              </div>

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

                {editorExecutionId !== null && (
                  <QueryStatusBar
                    status={activeStatus}
                    isInFlight={activeIsInFlight}
                    startedAt={activeRun?.startedAt ?? null}
                    batch={
                      activeRun && activeRun.statements.length > 1
                        ? {current: activeRun.currentIndex + 1, total: activeRun.statements.length}
                        : undefined
                    }
                    rowCount={displayExecutionId !== null ? results.loadedRowCount : undefined}
                    hasMoreRows={results.hasMoreServer}
                    hasResultSet={hasResultSet}
                    totalRowCount={rowCount.total}
                    canSaveResults={canSaveResults}
                    onSaveResults={() => setSaveResultsOpen(true)}
                  />
                )}

                {showError && editorOwnsRun && (
                  <div className="px-5 pt-4">
                    <Banner
                      variant="danger"
                      title="Query failed."
                      onDismiss={() => dismissError(activeTabId)}>
                      {/* SPEC-106 FR-004: friendly, mapped guidance — no raw Athena
                      engine text (the raw reason is dev-logged + kept in history). */}
                      <p className="text-sm">{errorMessage}</p>
                    </Banner>
                  </div>
                )}

                <div className={cx('flex min-h-0 flex-1 flex-col overflow-hidden px-5 py-4')}>
                  {/* SPEC-078 FR-007: the tab-per-statement scope gets a result-tab
                  strip; the other scopes render a single result view. Tabs are
                  ephemeral — a new run replaces the tab's run state wholesale. */}
                  {showResultTabs && activeRun && (
                    <ResultTabs
                      tabs={activeRun.resultTabs}
                      activeIndex={activeRun.activeResultTabIndex}
                      onSelect={(index) => selectResultTab(activeTabId, index)}
                    />
                  )}
                  {/* SPEC-087 FR-002: the Results header row carries the "Rows per
                  page" control — above the grid, right under the status bar's
                  row-count stat, and always rendered (disabled, never hidden,
                  when there's no result set to page). */}
                  <div className="mb-3 flex flex-none flex-wrap items-center justify-between gap-3">
                    <h2 className="text-base font-semibold">Results</h2>
                    <ResultsPageSizeControl
                      pageSize={resultsPageSize.pageSize}
                      onCommit={resultsPageSize.setPageSize}
                      disabled={!hasResultSet || !editorOwnsRun}
                    />
                  </div>
                  {editorDisplayExecutionId !== null ? (
                    <div
                      className="flex min-h-0 flex-1 flex-col"
                      {...(showResultTabs &&
                        activeRun && {
                          role: 'tabpanel',
                          id: 'result-tabpanel',
                          'aria-labelledby': `result-tab-${activeRun.activeResultTabIndex}`
                        })}>
                      <QueryResultsTable
                        columns={results.columns}
                        rows={results.rows}
                        pageIndex={results.pageIndex}
                        rangeStart={results.rangeStart}
                        rangeEnd={results.rangeEnd}
                        totalRowCount={results.totalRowCount}
                        hasPrev={results.hasPrev}
                        hasNext={results.hasNext}
                        isFetchingNext={results.isFetchingNext}
                        isLoading={results.isPending}
                        widths={colWidths.widths}
                        onResize={colWidths.setWidth}
                        onResetColumn={colWidths.resetColumn}
                        onPrev={results.goPrev}
                        onNext={results.goNext}
                      />
                    </div>
                  ) : (
                    <p className="flex h-full items-center justify-center text-sm text-text-3">
                      {/* A disowned run isn't this buffer's to narrate — but while
                          it holds the tab it locks the toolbar, so silence would
                          leave that unexplained. */}
                      {activeIsInFlight
                        ? editorOwnsRun
                          ? 'Running your query…'
                          : 'A query you started on a smaller screen is still running.'
                        : editorOwnsRun && activeBatchDone && activeStatus?.state === 'SUCCEEDED'
                          ? 'The run finished without returning rows.'
                          : 'Run a query to see results.'}
                    </p>
                  )}
                </div>
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

      {clearOpen && (
        <ClearQueryDialog
          onConfirm={handleClearConfirm}
          onCancel={() => setClearOpen(false)}
        />
      )}
      {saveOpen && (
        <SaveQueryDialog
          initialName={activeLinkedSaved?.name ?? ''}
          savedQueries={saved.queries}
          linkedId={activeTab.savedQueryId}
          onSave={handleSaveConfirm}
          onCancel={() => setSaveOpen(false)}
        />
      )}
      {closing && (
        <CloseTabDialog
          label={closing.label}
          onConfirm={confirmClose}
          onCancel={() => setClosing(null)}
        />
      )}
      {limitOpen && <TabLimitDialog onDismiss={() => setLimitOpen(false)} />}
      {createViewOpen && (
        <CreateViewDialog
          busy={ddl.busy}
          targetDatabase={createViewDb}
          onCreate={handleCreateView}
          onCancel={() => setCreateViewOpen(false)}
        />
      )}
      {share.target && (
        <TableShareDialog
          source={share.target}
          busy={share.busy}
          submitError={share.error}
          onSubmit={(args) => void share.submit(args)}
          onCancel={share.close}
        />
      )}
      {refresh.target && (
        <RefreshTableDialog
          target={refresh.target}
          busy={refresh.busy}
          submitError={refresh.error}
          onConfirm={(allowRemovals) => void refresh.submit(allowRemovals)}
          onCancel={refresh.close}
        />
      )}
      {dropping && (
        <DropTableDialog
          table={dropping.table.name}
          isDropping={ddl.busy}
          isView={dropping.table.tableType === 'VIRTUAL_VIEW'}
          onConfirm={handleDropConfirm}
          onCancel={() => setDropping(null)}
        />
      )}
      {saveResultsOpen && saveSpaces.length > 0 && (
        <SaveResultsDialog
          spaces={saveSpaces}
          defaultName={savedResultsDefaultName}
          isBusy={saveInFlight}
          onSave={handleSaveResults}
          onCancel={() => setSaveResultsOpen(false)}
        />
      )}
      {overwritePrompt && (
        <ConfirmDialog
          title={`Overwrite “${overwritePrompt.filename}”?`}
          ariaLabel="Confirm overwrite"
          confirmLabel="Overwrite"
          confirmVariant="danger"
          busy={saveInFlight}
          busyLabel="Saving…"
          onConfirm={() =>
            doSaveCopy({
              sourceBucket: overwritePrompt.sourceBucket,
              sourceKey: overwritePrompt.sourceKey,
              destBucket: overwritePrompt.destBucket,
              destPrefix: overwritePrompt.destPrefix,
              filename: overwritePrompt.filename,
              overwrite: true
            })
          }
          onCancel={() => {
            setOverwritePrompt(null);
            setSaveResultsOpen(true); // return to the dialog with the name editable
          }}>
          <p className="mt-3 text-sm text-text-2">
            A file named “{overwritePrompt.filename}” already exists in that folder. Saving will replace it.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
