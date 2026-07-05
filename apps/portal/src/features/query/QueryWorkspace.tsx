import {Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {Button} from '../../components/Button';
import {Banner} from '../../components/Banner';
import {cx} from '../../lib/cx';
import {runQuery, stopQuery, getTableDdl, runStatementToCompletion, parseS3Url, isTerminalState} from './query.service';
import {copyObject} from '../file-browser/fileBrowser.service';
import {invalidateListing} from '../../lib/queryClient';
import {TABLE_PREVIEW_ROW_LIMIT} from './query.constants';
import {useQueryExecution} from './useQueryExecution';
import {useQueryResults} from './useQueryResults';
import {useResultsPageSize} from './useResultsPageSize';
import {ResultsPageSizeControl} from './ResultsPageSizeControl';
import {useResultRowCount} from './useResultRowCount';
import {useColumnWidths} from './useColumnWidths';
import {useQueryHistory} from './useQueryHistory';
import {useQueryTabs} from './useQueryTabs';
import {useEditorLayout} from './useEditorLayout';
import {EditorLayoutControl} from './EditorLayoutControl';
import {useSavedQueries} from './useSavedQueries';
import {useConnections} from './useConnections';
import {invalidateSchema, useAllSchemas} from './useSchema';
import {
  deriveViewTargetDatabase,
  isResultProducingSql,
  resolveRunStatements,
  sameSql,
  schemaChangingDatabase,
  splitSqlStatements,
  statementHint,
  stripTrailingSemicolons
} from './query.sql';
import {ResultTabs} from './ResultTabs';
import {SchemaBrowser} from './SchemaBrowser';
import {DropTableDialog} from './DropTableDialog';
import {CreateViewDialog} from './CreateViewDialog';
import {SaveResultsDialog, type DestinationSpace} from './SaveResultsDialog';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {Toast, type ToastState} from './Toast';
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
import {isConnectionUsable} from './query.types';
import type {
  ParsedStatement,
  QueryHistoryEntry,
  QueryStatus,
  QueryTab,
  ResultTab,
  RunScope,
  SavedQuery,
  GlueTableSummary
} from './query.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it (SPEC-035 FR-003).
const SqlEditor = lazy(() => import('./SqlEditor').then((m) => ({default: m.SqlEditor})));

// SPEC-041: per-tab in-memory run state (not persisted — results re-fetch on a
// fresh Run). SPEC-078 extends it to a sequential batch: the statements in
// scope, the in-flight statement's execution, and the result tabs accumulated
// as result-producing statements succeed. `submittedSql` is the CURRENT
// statement's text, kept so the background finalizer can decide whether a
// succeeded DDL should refresh the schema.
type TabRun = {
  scope: RunScope;
  /** The statements in scope, execution order (length >= 1). */
  statements: ParsedStatement[];
  /** 0-based index of the statement `executionId` belongs to. */
  currentIndex: number;
  executionId: string;
  /** Batch start — the elapsed timer spans the whole batch. */
  startedAt: number;
  submittedSql: string;
  /** One entry per result-producing statement that has SUCCEEDED, in order. */
  resultTabs: ResultTab[];
  activeResultTabIndex: number;
  /** The batch reached a terminal state (success, failure, or Stop). */
  done: boolean;
  /** Stop was pressed — the finalizer must not start the next statement. */
  halted?: boolean;
  /** Set when a statement failed (or failed to start); drives the banner. */
  failure?: {statementIndex: number; reason: string};
  /** Saved-query link captured at submit, recorded on every statement's history entry. */
  savedQuery?: {id: string; name: string};
};

// SPEC-041 FR-004: a headless poller, one per tab holding an execution. Each runs
// its own useQueryExecution so a backgrounded query keeps polling to terminal
// (its status/history finalize without waiting for the user to return). Reports
// status up and finalizes history exactly once per execution id.
function TabExecutionPoller({
  tabId,
  executionId,
  submittedSql,
  onStatus,
  onFinalize
}: {
  tabId: string;
  executionId: string;
  submittedSql: string;
  onStatus: (tabId: string, status: QueryStatus | undefined) => void;
  onFinalize: (tabId: string, executionId: string, status: QueryStatus, sql: string) => void;
}) {
  const execution = useQueryExecution(executionId);
  const status = execution.data;
  const finalizedRef = useRef<string | null>(null);

  useEffect(() => {
    onStatus(tabId, status);
  }, [tabId, status, onStatus]);

  useEffect(() => {
    if (!status || !isTerminalState(status.state)) return;
    if (finalizedRef.current === executionId) return;
    finalizedRef.current = executionId;
    onFinalize(tabId, executionId, status, submittedSql);
  }, [tabId, status, executionId, submittedSql, onFinalize]);

  return null;
}

// SPEC-035 query workspace (FR-002): schema browser (left) + editor/status/results
// (main), wired to the SPEC-034 data layer. SPEC-041 makes the editor multi-tab:
// each tab is an independent query window with its own SQL + run state; Run/Clear/
// Stop/status/results all act on the active tab.
export function QueryWorkspace() {
  const {user} = useAuth();
  const username = user?.username ?? '';
  const queryClient = useQueryClient();
  // SPEC-049: the user-space bucket (also where Athena writes results) — the
  // Save-results copy stays within it.
  const userSpaceBucket = import.meta.env.VITE_S3_USER_SPACE_BUCKET as string | undefined;
  // SPEC-055: the shared-space bucket (where shared-DB results land + a Save target).
  const sharedSpaceBucket = import.meta.env.VITE_S3_SHARED_SPACE_BUCKET as string | undefined;

  // SPEC-077: there is no active database. The rail browses every accessible
  // database; queries carry no execution context and must fully-qualify every
  // base table. `useConnections` still enumerates the browsable/queryable spaces.
  const {connections} = useConnections(username || null);
  // Every usable database, for the browse rail + multi-database autocomplete.
  const usableDatabases = useMemo(() => connections.filter(isConnectionUsable).map((c) => c.database), [connections]);
  // SPEC-077 FR-005: autocomplete offers fully-qualified names across every
  // accessible database (shares the schema cache with the expandable rail nodes).
  const completionSchemas = useAllSchemas(usableDatabases);

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

  // Per-tab run state, keyed by tab id (in-memory for the session). The ref is
  // the synchronous source of truth (every write goes through updateRuns, from
  // event handlers/effects only — never render): the batch finalizer and the
  // Stop handler read/write it without waiting for a commit, so a Stop is
  // visible to an in-flight advancement immediately. State mirrors it for render.
  const [runs, setRuns] = useState<Record<string, TabRun>>({});
  const runsRef = useRef(runs);
  const updateRuns = useCallback((updater: (prev: Record<string, TabRun>) => Record<string, TabRun>) => {
    runsRef.current = updater(runsRef.current);
    setRuns(runsRef.current);
  }, []);
  const [statuses, setStatuses] = useState<Record<string, QueryStatus | undefined>>({});
  const [runErrors, setRunErrors] = useState<Record<string, string | null>>({});
  const [dismissed, setDismissed] = useState<Record<string, boolean>>({});

  // Drawers are mutually exclusive (FR-010): opening one closes the other.
  const [historyOpen, setHistoryOpen] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [limitOpen, setLimitOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [closing, setClosing] = useState<QueryTab | null>(null);
  // SPEC-044 table actions.
  const [dropping, setDropping] = useState<{database: string; table: GlueTableSummary} | null>(null);
  const [dropInFlight, setDropInFlight] = useState(false);
  const [toast, setToast] = useState<(ToastState & {action?: {label: string; onClick: () => void}}) | null>(null);
  // SPEC-048: Create view. SPEC-077: the target database derived from the body.
  const [createViewOpen, setCreateViewOpen] = useState(false);
  const [createViewDb, setCreateViewDb] = useState('');
  const [createViewInFlight, setCreateViewInFlight] = useState(false);
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
  // Tabs whose run has been submitted but not yet recorded in `runs` (SPEC-083 FR-009).
  // The de-dupe guard reads this ref so a rapid double-trigger de-dupes before the
  // async setRuns commits, which the runs/statuses render snapshot alone can miss.
  const submittingTabsRef = useRef<Set<string>>(new Set());

  const {appendEntry, updateEntry} = useQueryHistory(username || null);
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
  const showResultTabs = activeRun?.scope === 'script-tabs' && activeBatchDone && activeRun.resultTabs.length > 0;

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

  // Stable callbacks for the per-tab pollers.
  const handleStatus = useCallback((tabId: string, status: QueryStatus | undefined) => {
    setStatuses((s) => (s[tabId] === status ? s : {...s, [tabId]: status}));
  }, []);
  const handleFinalize = useCallback(
    (tabId: string, executionId: string, status: QueryStatus, sql: string) => {
      updateEntry({
        queryExecutionId: executionId,
        patch: {
          status: status.state,
          dataScannedBytes: status.dataScannedBytes,
          durationMs: status.engineExecutionTimeMillis
        }
      }).catch((e) => console.warn('[query-history] update failed', e));

      // SPEC-077: a user-typed DDL fully-qualifies its own target; refresh that
      // database's schema (there's no active database to assume).
      const ddlDb = status.state === 'SUCCEEDED' ? schemaChangingDatabase(sql) : null;
      if (ddlDb) void invalidateSchema(queryClient, ddlDb);

      // ── SPEC-078: batch bookkeeping + advancement ─────────────────────────
      const run = runsRef.current[tabId];
      // Stale finalize (tab closed, or a new run replaced this one) — history
      // above is still recorded; there is no batch to advance.
      if (!run || run.done || run.executionId !== executionId) return;

      // FR-007: a result-producing statement that succeeded earns a result tab
      // (accumulated in every scope; display differs by scope).
      const resultTab: ResultTab | null =
        status.state === 'SUCCEEDED' && isResultProducingSql(sql)
          ? {
              statementIndex: run.currentIndex,
              executionId,
              label: `${run.currentIndex + 1} · ${statementHint(sql)}`,
              outputLocation: status.outputLocation
            }
          : null;
      const withResult = (cur: TabRun): TabRun => {
        // Idempotent: at most one result tab per execution, so a re-applied
        // updater can never duplicate a tab.
        const resultTabs =
          resultTab && !cur.resultTabs.some((t) => t.executionId === resultTab.executionId)
            ? [...cur.resultTabs, resultTab]
            : cur.resultTabs;
        return {...cur, resultTabs, activeResultTabIndex: Math.max(0, resultTabs.length - 1)};
      };
      // Guarded batch update: only applies while this execution is still the
      // tab's current one (the tab may close or start a new run meanwhile).
      const patchRun = (patch: (cur: TabRun) => TabRun) => {
        updateRuns((r) => {
          const cur = r[tabId];
          if (!cur || cur.executionId !== executionId) return r;
          return {...r, [tabId]: patch(withResult(cur))};
        });
      };

      // FR-002: stop at the first non-SUCCEEDED terminal state, and never
      // advance past a Stop even when the statement outran the cancel.
      const hasNext = run.currentIndex < run.statements.length - 1;
      if (status.state !== 'SUCCEEDED' || !hasNext || run.halted) {
        patchRun((cur) => ({
          ...cur,
          done: true,
          ...(status.state === 'FAILED' && {
            failure: {
              statementIndex: cur.currentIndex,
              reason: status.stateChangeReason ?? 'The query failed.'
            }
          })
        }));
        return;
      }

      // Start the next statement through the same machinery: the tab's poller
      // picks up the new execution id and finalizes it in turn.
      const next = run.statements[run.currentIndex + 1];
      void (async () => {
        const started = await runQuery({sql: next.sql, username});
        if (!started.success) {
          patchRun((cur) => ({
            ...cur,
            done: true,
            failure: {statementIndex: next.index, reason: started.error.message}
          }));
          return;
        }
        const nextId = started.data.queryExecutionId;
        // Stop, tab close, or a replacing run landed while the next statement
        // was starting — cancel it and settle the batch instead of installing
        // it (otherwise it would run with no poller attached and its history
        // entry would never finalize).
        const latest = runsRef.current[tabId];
        if (!latest || latest.halted || latest.executionId !== executionId) {
          void stopQuery(nextId);
          patchRun((cur) => ({...cur, done: true}));
          return;
        }
        // Reset the prior statement's terminal status so the UI shows the new
        // one as running immediately.
        setStatuses((s) => ({...s, [tabId]: undefined}));
        // Same history race guard as the first statement: the entry must land
        // before the poller's finalizer can read-modify-write it (FR-003).
        await appendEntry({
          queryExecutionId: nextId,
          sql: next.sql,
          database: username,
          submittedAt: new Date().toISOString(),
          ...(run.savedQuery && {
            savedQueryId: run.savedQuery.id,
            savedQueryName: run.savedQuery.name
          })
        }).catch((e) => console.warn('[query-history] append failed', e));
        patchRun((cur) => ({
          ...cur,
          executionId: nextId,
          currentIndex: cur.currentIndex + 1,
          submittedSql: next.sql
        }));
      })();
    },
    [updateEntry, queryClient, username, appendEntry, updateRuns]
  );

  // Submit a batch of statements into a tab (defaults to the active tab),
  // starting the FIRST statement; the finalizer advances through the rest
  // sequentially (SPEC-078 FR-002). An explicit tabId lets a just-opened tab
  // (View data, SPEC-044) auto-run into itself before the activeTabId state
  // change has committed. A new run replaces the tab's prior run wholesale, so
  // the previous batch's result tabs are cleared (FR-007).
  const submitBatch = (statements: ParsedStatement[], scope: RunScope, tabId: string = activeTabId) => {
    if (statements.length === 0) return;
    // De-dupe guard. The ref reflects a submit already in flight for this tab even
    // before its `runs` entry commits, so a rapid double-trigger (e.g. View data
    // opens a tab and calls submit in the same tick) starts at most one execution.
    if (submittingTabsRef.current.has(tabId)) return;
    // Read the ref, not the render snapshot — it reflects a run installed in
    // this same tick (the submittingTabsRef guard is released before re-render).
    const existing = runsRef.current[tabId];
    if (existing && !existing.done) return;
    submittingTabsRef.current.add(tabId);

    // SPEC-043 FR-009: a run from a tab linked to a saved query records that
    // query's id/name in history. Captured from the active tab at submit time.
    const linkedId = tabs.tabs.find((t) => t.id === tabId)?.savedQueryId;
    const linkedSaved = linkedId ? savedById.get(linkedId) : undefined;

    setRunErrors((e) => ({...e, [tabId]: null}));
    setDismissed((d) => ({...d, [tabId]: false}));
    void (async () => {
      try {
        const first = statements[0];
        // SPEC-077: no execution database context — the query fully-qualifies its
        // own tables. Results land in the personal prefix (runQuery's default); a
        // shared destination is chosen explicitly at Save time (SPEC-049/055).
        const result = await runQuery({
          sql: first.sql,
          username
        });
        if (!result.success) {
          setRunErrors((e) => ({...e, [tabId]: result.error.message}));
          return;
        }
        const id = result.data.queryExecutionId;
        // Reset any prior terminal status so the UI shows "running" immediately.
        setStatuses((s) => ({...s, [tabId]: undefined}));
        // Persist the history entry BEFORE recording the run (which mounts the
        // poller). The finalizer's updateEntry is a read-modify-write, so if the
        // append hasn't landed yet it would read a history without this entry and
        // no-op — losing the terminal status and leaving history looking empty/
        // stale. Awaiting the append closes that race for fast queries.
        await appendEntry({
          queryExecutionId: id,
          sql: first.sql,
          // SPEC-077 FR-006: informational only (there's no active database). The
          // personal database is the fixed default context recorded for display.
          database: username,
          submittedAt: new Date().toISOString(),
          ...(linkedSaved && {
            savedQueryId: linkedSaved.id,
            savedQueryName: linkedSaved.name
          })
        }).catch((e) => console.warn('[query-history] append failed', e));
        updateRuns((r) => ({
          ...r,
          [tabId]: {
            scope,
            statements,
            currentIndex: 0,
            executionId: id,
            startedAt: Date.now(),
            submittedSql: first.sql,
            resultTabs: [],
            activeResultTabIndex: 0,
            done: false,
            ...(linkedSaved && {savedQuery: {id: linkedSaved.id, name: linkedSaved.name}})
          }
        }));
      } finally {
        // Hand off to the state-based guard: once `runs[tabId]` commits (success) or
        // the run errored (retryable), the ref no longer needs to block.
        submittingTabsRef.current.delete(tabId);
      }
    })();
  };

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

  // FR-002: Stop cancels the in-flight statement AND halts the remainder. The
  // halted flag is set first so the finalizer never starts the next statement,
  // even when the current one outruns the cancel and SUCCEEDs.
  const handleStop = () => {
    const run = runsRef.current[activeTabId];
    if (!run || run.done) return;
    updateRuns((r) => {
      const cur = r[activeTabId];
      if (!cur || cur.done) return r;
      return {...r, [activeTabId]: {...cur, halted: true}};
    });
    void stopQuery(run.executionId); // poller observes CANCELLED
  };

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
        setToast({
          variant: 'danger',
          message: `Couldn’t save results: ${result.error.message}`
        });
        return;
      }
      setSaveResultsOpen(false);
      setOverwritePrompt(null);
      void invalidateListing(queryClient, args.destBucket, args.destPrefix);
      // SPEC-055: the Files browser only renders the personal space until SPEC-057,
      // so the "View in Files" deep-link is offered only for a personal-space save.
      const isPersonalDest = args.destBucket === userSpaceBucket;
      setToast({
        variant: 'success',
        message: `Saved to ${args.destPrefix}${args.filename}`,
        ...(isPersonalDest && {
          action: {
            label: 'View in Files',
            onClick: () => {
              setToast(null);
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
      setToast({
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

  // FR-005: drop the closed tab's in-memory run state (its execution keeps running
  // server-side; history is the durable record).
  const dropRunState = (id: string) => {
    const without = <T,>(m: Record<string, T>) => {
      const next = {...m};
      delete next[id];
      return next;
    };
    updateRuns(without);
    setStatuses(without);
    setRunErrors(without);
    setDismissed(without);
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
    saved.upsert(query).catch((e) => console.warn('[saved-queries] save failed', e));
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
    saved.remove(id).catch((e) => console.warn('[saved-queries] delete failed', e));
    tabs.unlinkSavedQuery(id);
  };

  // ── SPEC-044 table actions ──────────────────────────────────────────────
  // Derive the in-space S3 key (folder) backing a table from its Glue LOCATION;
  // null when missing or outside the user's own prefix (FR-002 guard).
  const tablePrefix = (table: GlueTableSummary): string | null => {
    if (!table.location) return null;
    const match = /^s3:\/\/[^/]+\/(.+)$/.exec(table.location);
    if (!match) return null;
    const key = match[1].endsWith('/') ? match[1] : `${match[1]}/`;
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
      setToast({variant: 'info', message: `Loading DDL for ${table.name}…`});
      void (async () => {
        const result = await getTableDdl({
          database,
          table: table.name,
          username,
          isView: table.tableType === 'VIRTUAL_VIEW'
        });
        if (!result.success) {
          setToast({
            variant: 'danger',
            message: `Couldn’t load DDL: ${result.error.message}`
          });
          return;
        }
        setToast(null);
        const id = tabs.openTab({
          label: `DDL: ${table.name}`,
          sql: result.data
        });
        if (id === null) setLimitOpen(true);
        else editorRef.current?.focus();
      })();
    },
    // Open a "{table}" tab pre-filled with a fully-qualified SELECT * LIMIT N + auto-run.
    onViewData: (database: string, table: GlueTableSummary) => {
      const sql = `SELECT * FROM ${database}.${table.name} LIMIT ${TABLE_PREVIEW_ROW_LIMIT}`;
      const id = tabs.openTab({label: table.name, sql});
      if (id === null) {
        setLimitOpen(true);
        return;
      }
      editorRef.current?.focus();
      submitBatch(splitSqlStatements(sql), 'script-single', id); // auto-run into the just-opened tab
    },
    // Confirm, then drop in the background (handled on confirm) — carries the node's db.
    onDropTable: (database: string, table: GlueTableSummary) => setDropping({database, table})
  };

  // SPEC-048/077: turn the active tab's SQL into a named view, in the background
  // (the editor keeps showing the user's SELECT). The target database is derived
  // from the view body's fully-qualified base tables (FR-008), captured in
  // `createViewDb` when the dialog opened.
  const handleCreateView = (name: string) => {
    const database = createViewDb;
    if (!database) return;
    const body = stripTrailingSemicolons(activeTab.sql);
    const sql = `CREATE OR REPLACE VIEW ${database}.${name} AS ${body}`;
    setCreateViewInFlight(true);
    void (async () => {
      const result = await runStatementToCompletion({sql, database, username});
      setCreateViewInFlight(false);
      setCreateViewOpen(false);
      if (!result.success) {
        setToast({
          variant: 'danger',
          message: `Couldn’t create view ${name}: ${result.error.message}`
        });
        return;
      }
      const status = result.data;
      // Record the run in history (a CREATE VIEW is a real statement).
      appendEntry({
        queryExecutionId: status.queryExecutionId,
        sql,
        database,
        submittedAt: new Date().toISOString(),
        status: status.state,
        dataScannedBytes: status.dataScannedBytes,
        durationMs: status.engineExecutionTimeMillis
      }).catch((e) => console.warn('[query-history] append failed', e));

      if (status.state === 'SUCCEEDED') {
        void invalidateSchema(queryClient, database);
        setToast({variant: 'success', message: `Created view ${name}`});
      } else {
        setToast({
          variant: 'danger',
          message: `Couldn’t create view ${name}: ${status.stateChangeReason ?? 'Create view failed'}`
        });
      }
    })();
  };

  const handleDropConfirm = () => {
    if (!dropping) return;
    const {database, table} = dropping;
    const isView = table.tableType === 'VIRTUAL_VIEW';
    const sql = `DROP ${isView ? 'VIEW' : 'TABLE'} ${database}.${table.name}`;
    setDropInFlight(true);
    void (async () => {
      const result = await runStatementToCompletion({
        sql,
        database,
        username
      });
      setDropInFlight(false);
      setDropping(null);
      if (!result.success) {
        setToast({
          variant: 'danger',
          message: `Couldn’t drop ${table.name}: ${result.error.message}`
        });
        return;
      }
      const status = result.data;
      // Record the drop in history (FR-005).
      appendEntry({
        queryExecutionId: status.queryExecutionId,
        sql,
        database,
        submittedAt: new Date().toISOString(),
        status: status.state,
        dataScannedBytes: status.dataScannedBytes,
        durationMs: status.engineExecutionTimeMillis
      }).catch((e) => console.warn('[query-history] append failed', e));

      if (status.state === 'SUCCEEDED') {
        void invalidateSchema(queryClient, database);
        setToast({variant: 'success', message: `Dropped ${table.name}`});
      } else {
        setToast({
          variant: 'danger',
          message: `Couldn’t drop ${table.name}: ${status.stateChangeReason ?? 'Drop failed'}`
        });
      }
    })();
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
    return `Statement ${at} of ${total} failed: ${run.failure.reason}.${skippedNote}`;
  })();
  const errorMessage =
    runErrors[activeTabId] ??
    batchFailureMessage ??
    (activeStatus?.state === 'FAILED' ? (activeStatus.stateChangeReason ?? 'The query failed.') : null);
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
      <SchemaBrowser
        connections={connections}
        actions={tableActions}
      />

      {/* Background pollers — one per tab with an execution, so backgrounded
          queries finalize concurrently (FR-004). They render nothing. */}
      {Object.entries(runs).map(([tabId, run]) => (
        <TabExecutionPoller
          key={tabId}
          tabId={tabId}
          executionId={run.executionId}
          submittedSql={run.submittedSql}
          onStatus={handleStatus}
          onFinalize={handleFinalize}
        />
      ))}

      <main
        id="main"
        className="flex min-h-0 min-w-0 flex-1 flex-col">
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
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4"
                aria-hidden="true">
                <path d="M3 6h18" />
                <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
              </svg>
              Clear
            </Button>
            <Button
              variant="ghost"
              onClick={() => setSaveOpen(true)}
              disabled={!canSave}
              aria-label="Save query">
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
              Save
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                // FR-008: derive the target database from the view body before
                // opening the dialog; a non-derivable body raises a clear error
                // and never silently picks a database.
                const target = deriveViewTargetDatabase(stripTrailingSemicolons(activeTab.sql));
                if ('error' in target) {
                  setToast({variant: 'danger', message: target.error});
                  return;
                }
                setCreateViewDb(target.database);
                setCreateViewOpen(true);
              }}
              disabled={!canSave}
              aria-label="Create view">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4"
                aria-hidden="true">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                <circle
                  cx="12"
                  cy="12"
                  r="3"
                />
              </svg>
              Create view
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
                Stop
              </Button>
            ) : (
              // SPEC-078 FR-005: three distinct run scopes. Run Statement stays
              // the primary action on ⌘⏎; the two whole-script scopes differ
              // only in how results are shown (single view vs tab per statement).
              <>
                <Button
                  variant="ghost"
                  onClick={() => handleRunScript('script-single')}
                  disabled={!canRun}
                  title="Run every statement; show the last result (⌘⇧⏎)"
                  aria-label="Run script, single result">
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
                  Run Script (single result)
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => handleRunScript('script-tabs')}
                  disabled={!canRun}
                  title="Run every statement; one result tab per statement (⌘⌥⏎)"
                  aria-label="Run script, tab per statement">
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
                  Run Script (tab per statement)
                </Button>
                <Button
                  variant="primary"
                  onClick={handleRunStatement}
                  disabled={!canRun}
                  title="Run the selection or the statement under the cursor (⌘⏎)"
                  aria-label="Run statement">
                  <svg
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    stroke="none"
                    className="h-4 w-4"
                    aria-hidden="true">
                    <path d="M7 5v14l11-7z" />
                  </svg>
                  Run Statement
                </Button>
              </>
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

            {activeExecutionId !== null && (
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
                atRowCeiling={rowCount.atCeiling}
                canSaveResults={canSaveResults}
                onSaveResults={() => setSaveResultsOpen(true)}
              />
            )}

            {showError && (
              <div className="px-5 pt-4">
                <Banner
                  variant="danger"
                  title="Query failed."
                  onDismiss={() => {
                    setRunErrors((e) => ({...e, [activeTabId]: null}));
                    setDismissed((d) => ({...d, [activeTabId]: true}));
                  }}>
                  <code className="font-mono text-xs">{errorMessage}</code>
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
                  onSelect={(index) =>
                    updateRuns((r) =>
                      r[activeTabId] ? {...r, [activeTabId]: {...r[activeTabId], activeResultTabIndex: index}} : r
                    )
                  }
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
                  disabled={!hasResultSet}
                />
              </div>
              {displayExecutionId !== null ? (
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
                  {activeIsInFlight
                    ? 'Running your query…'
                    : activeBatchDone && activeStatus?.state === 'SUCCEEDED'
                      ? 'The run finished without returning rows.'
                      : 'Run a query to see results.'}
                </p>
              )}
            </div>
          </div>
        </div>
      </main>

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
          busy={createViewInFlight}
          targetDatabase={createViewDb}
          onCreate={handleCreateView}
          onCancel={() => setCreateViewOpen(false)}
        />
      )}
      {dropping && (
        <DropTableDialog
          table={dropping.table.name}
          isDropping={dropInFlight}
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
      {toast && (
        <Toast
          variant={toast.variant}
          message={toast.message}
          action={toast.action}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  );
}
