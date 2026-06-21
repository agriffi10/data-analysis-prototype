import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../auth';
import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { cx } from '../../lib/cx';
import {
  runQuery,
  stopQuery,
  getResultCsvUrl,
  getTableDdl,
  runStatementToCompletion,
  isTerminalState,
} from './query.service';
import { TABLE_PREVIEW_ROW_LIMIT } from './query.constants';
import { useQueryExecution } from './useQueryExecution';
import { useQueryResults } from './useQueryResults';
import { useQueryHistory } from './useQueryHistory';
import { useQueryTabs } from './useQueryTabs';
import { useSavedQueries } from './useSavedQueries';
import { invalidateSchema } from './useSchema';
import { isSchemaChangingSql, sameSql } from './query.sql';
import { SchemaBrowser } from './SchemaBrowser';
import { DropTableDialog } from './DropTableDialog';
import { Toast, type ToastState } from './Toast';
import { QueryStatusBar } from './QueryStatusBar';
import { QueryResultsTable } from './QueryResultsTable';
import { QueryHistoryPanel } from './QueryHistoryPanel';
import { SavedQueriesPanel } from './SavedQueriesPanel';
import { QueryTabStrip } from './QueryTabStrip';
import { ClearQueryDialog } from './ClearQueryDialog';
import { CloseTabDialog } from './CloseTabDialog';
import { TabLimitDialog } from './TabLimitDialog';
import { SaveQueryDialog } from './SaveQueryDialog';
import type { SqlEditorHandle } from './SqlEditor';
import type {
  QueryHistoryEntry,
  QueryStatus,
  QueryTab,
  SavedQuery,
  GlueTableSummary,
} from './query.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it (SPEC-035 FR-003).
const SqlEditor = lazy(() =>
  import('./SqlEditor').then((m) => ({ default: m.SqlEditor })),
);

// SPEC-041: per-tab in-memory run state (not persisted — results re-fetch on a
// fresh Run). `submittedSql` is kept so the background finalizer can decide
// whether a succeeded DDL should refresh the schema.
type TabRun = {
  executionId: string;
  startedAt: number;
  submittedSql: string;
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
  onFinalize,
}: {
  tabId: string;
  executionId: string;
  submittedSql: string;
  onStatus: (tabId: string, status: QueryStatus | undefined) => void;
  onFinalize: (executionId: string, status: QueryStatus, sql: string) => void;
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
    onFinalize(executionId, status, submittedSql);
  }, [status, executionId, submittedSql, onFinalize]);

  return null;
}

// SPEC-035 query workspace (FR-002): schema browser (left) + editor/status/results
// (main), wired to the SPEC-034 data layer. SPEC-041 makes the editor multi-tab:
// each tab is an independent query window with its own SQL + run state; Run/Clear/
// Stop/status/results all act on the active tab.
export function QueryWorkspace() {
  const { user } = useAuth();
  const username = user?.username ?? '';
  const database = username;
  const queryClient = useQueryClient();

  const tabs = useQueryTabs(username);
  const { activeTab, activeTabId } = tabs;

  // Per-tab run state, keyed by tab id (in-memory for the session).
  const [runs, setRuns] = useState<Record<string, TabRun>>({});
  const [statuses, setStatuses] = useState<Record<string, QueryStatus | undefined>>(
    {},
  );
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
  const [dropping, setDropping] = useState<GlueTableSummary | null>(null);
  const [dropInFlight, setDropInFlight] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const navigate = useNavigate();
  const editorRef = useRef<SqlEditorHandle>(null);

  const { appendEntry, updateEntry } = useQueryHistory(username || null);
  const saved = useSavedQueries(username || null);

  // SPEC-043 FR-008: a linked tab is "dirty" when its editor SQL differs from the
  // stored saved query. Drives the tab-strip marker.
  const savedById = new Map(saved.queries.map((q) => [q.id, q]));
  const dirtyTabIds = new Set(
    tabs.tabs
      .filter((t) => {
        const sq = t.savedQueryId ? savedById.get(t.savedQueryId) : undefined;
        return sq !== undefined && !sameSql(sq.sql, t.sql);
      })
      .map((t) => t.id),
  );
  const activeLinkedSaved = activeTab.savedQueryId
    ? savedById.get(activeTab.savedQueryId)
    : undefined;

  const openHistory = () => {
    setSavedOpen(false);
    setHistoryOpen(true);
  };
  const openSaved = () => {
    setHistoryOpen(false);
    setSavedOpen(true);
  };

  // Active-tab derived run state.
  const activeRun = runs[activeTabId];
  const activeExecutionId = activeRun?.executionId ?? null;
  const activeStatus = statuses[activeTabId];
  const activeIsInFlight =
    !!activeRun && (!activeStatus || !isTerminalState(activeStatus.state));
  const succeeded = activeStatus?.state === 'SUCCEEDED';

  // Results only fetch once the active query has succeeded; one page (≤20 rows)
  // at a time via the SPEC-038 pager.
  const results = useQueryResults(succeeded ? activeExecutionId : null);

  // Stable callbacks for the per-tab pollers.
  const handleStatus = useCallback(
    (tabId: string, status: QueryStatus | undefined) => {
      setStatuses((s) => (s[tabId] === status ? s : { ...s, [tabId]: status }));
    },
    [],
  );
  const handleFinalize = useCallback(
    (executionId: string, status: QueryStatus, sql: string) => {
      updateEntry({
        queryExecutionId: executionId,
        patch: {
          status: status.state,
          dataScannedBytes: status.dataScannedBytes,
          durationMs: status.engineExecutionTimeMillis,
        },
      }).catch((e) => console.warn('[query-history] update failed', e));

      if (status.state === 'SUCCEEDED' && database && isSchemaChangingSql(sql)) {
        void invalidateSchema(queryClient, database);
      }
    },
    [updateEntry, queryClient, database],
  );

  // Submit a SQL string into a tab (defaults to the active tab). An explicit
  // tabId lets a just-opened tab (View data, SPEC-044) auto-run into itself
  // before the activeTabId state change has committed.
  const submit = (sqlText: string, tabId: string = activeTabId) => {
    if (!sqlText.trim() || !database) return;
    const existing = runs[tabId];
    const inFlight =
      !!existing &&
      (!statuses[tabId] || !isTerminalState(statuses[tabId]!.state));
    if (inFlight) return;

    // SPEC-043 FR-009: a run from a tab linked to a saved query records that
    // query's id/name in history. Captured from the active tab at submit time.
    const linkedId = tabs.tabs.find((t) => t.id === tabId)?.savedQueryId;
    const linkedSaved = linkedId ? savedById.get(linkedId) : undefined;

    setRunErrors((e) => ({ ...e, [tabId]: null }));
    setDismissed((d) => ({ ...d, [tabId]: false }));
    void (async () => {
      const result = await runQuery({ sql: sqlText, database, username });
      if (!result.success) {
        setRunErrors((e) => ({ ...e, [tabId]: result.error.message }));
        return;
      }
      const id = result.data.queryExecutionId;
      // Reset any prior terminal status so the UI shows "running" immediately.
      setStatuses((s) => ({ ...s, [tabId]: undefined }));
      // Persist the history entry BEFORE recording the run (which mounts the
      // poller). The finalizer's updateEntry is a read-modify-write, so if the
      // append hasn't landed yet it would read a history without this entry and
      // no-op — losing the terminal status and leaving history looking empty/
      // stale. Awaiting the append closes that race for fast queries.
      await appendEntry({
        queryExecutionId: id,
        sql: sqlText,
        database,
        submittedAt: new Date().toISOString(),
        ...(linkedSaved && {
          savedQueryId: linkedSaved.id,
          savedQueryName: linkedSaved.name,
        }),
      }).catch((e) => console.warn('[query-history] append failed', e));
      setRuns((r) => ({
        ...r,
        [tabId]: { executionId: id, startedAt: Date.now(), submittedSql: sqlText },
      }));
    })();
  };

  const handleRun = () => submit(activeTab.sql);

  const handleStop = () => {
    if (!activeExecutionId) return;
    void stopQuery(activeExecutionId); // poller observes CANCELLED
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
    submit(entry.sql);
  };

  const handleDownloadCsv = () => {
    if (!activeExecutionId || !activeStatus?.outputLocation) return;
    void (async () => {
      const result = await getResultCsvUrl({
        queryExecutionId: activeExecutionId,
        outputLocation: activeStatus.outputLocation as string,
      });
      if (!result.success) {
        setRunErrors((e) => ({ ...e, [activeTabId]: result.error.message }));
        setDismissed((d) => ({ ...d, [activeTabId]: false }));
        return;
      }
      const link = document.createElement('a');
      link.href = result.data.url;
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
    })();
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
      const next = { ...m };
      delete next[id];
      return next;
    };
    setRuns(without);
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
  const handleSaveConfirm = ({
    name,
    targetId,
  }: {
    name: string;
    targetId: string | null;
  }) => {
    const now = new Date().toISOString();
    const existing = targetId ? savedById.get(targetId) : undefined;
    const query: SavedQuery = {
      id: targetId ?? crypto.randomUUID(),
      name,
      sql: activeTab.sql,
      database,
      createdAt: existing?.createdAt ?? now,
      updatedAt: now,
    };
    saved.upsert(query).catch((e) => console.warn('[saved-queries] save failed', e));
    tabs.setActiveTabMeta({ label: name, savedQueryId: query.id });
    setSaveOpen(false);
    editorRef.current?.focus();
  };

  // FR-006: open a saved query into a new linked tab (cap dialog honored).
  const handleOpenSaved = (q: SavedQuery) => {
    const id = tabs.openTab({ label: q.name, sql: q.sql, savedQueryId: q.id });
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
    saved
      .remove(id)
      .catch((e) => console.warn('[saved-queries] delete failed', e));
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

  const tableActions = {
    canViewSourceFiles: (table: GlueTableSummary) => tablePrefix(table) !== null,
    // FR-002: deep-link the file browser to the table's data folder.
    onViewSourceFiles: (table: GlueTableSummary) => {
      const key = tablePrefix(table);
      if (!key) return;
      navigate(`/files?prefix=${encodeURIComponent(key)}`);
    },
    // FR-003: SHOW CREATE TABLE → a new, non-run "DDL: {table}" tab.
    onViewDdl: (table: GlueTableSummary) => {
      if (!database) return;
      setToast({ variant: 'info', message: `Loading DDL for ${table.name}…` });
      void (async () => {
        const result = await getTableDdl({
          database,
          table: table.name,
          username,
        });
        if (!result.success) {
          setToast({
            variant: 'danger',
            message: `Couldn’t load DDL: ${result.error.message}`,
          });
          return;
        }
        setToast(null);
        const id = tabs.openTab({
          label: `DDL: ${table.name}`,
          sql: result.data,
        });
        if (id === null) setLimitOpen(true);
        else editorRef.current?.focus();
      })();
    },
    // FR-004: open a "{table}" tab pre-filled with SELECT * LIMIT N and auto-run.
    onViewData: (table: GlueTableSummary) => {
      const sql = `SELECT * FROM ${database}.${table.name} LIMIT ${TABLE_PREVIEW_ROW_LIMIT}`;
      const id = tabs.openTab({ label: table.name, sql });
      if (id === null) {
        setLimitOpen(true);
        return;
      }
      editorRef.current?.focus();
      submit(sql, id); // auto-run into the just-opened tab
    },
    // FR-005: confirm, then drop in the background (handled on confirm).
    onDropTable: (table: GlueTableSummary) => setDropping(table),
  };

  const handleDropConfirm = () => {
    if (!dropping || !database) return;
    const table = dropping;
    const sql = `DROP TABLE ${database}.${table.name}`;
    setDropInFlight(true);
    void (async () => {
      const result = await runStatementToCompletion({
        sql,
        database,
        username,
      });
      setDropInFlight(false);
      setDropping(null);
      if (!result.success) {
        setToast({
          variant: 'danger',
          message: `Couldn’t drop ${table.name}: ${result.error.message}`,
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
        durationMs: status.engineExecutionTimeMillis,
      }).catch((e) => console.warn('[query-history] append failed', e));

      if (status.state === 'SUCCEEDED') {
        void invalidateSchema(queryClient, database);
        setToast({ variant: 'success', message: `Dropped ${table.name}` });
      } else {
        setToast({
          variant: 'danger',
          message: `Couldn’t drop ${table.name}: ${status.stateChangeReason ?? 'Drop failed'}`,
        });
      }
    })();
  };

  const errorMessage =
    runErrors[activeTabId] ??
    (activeStatus?.state === 'FAILED'
      ? (activeStatus.stateChangeReason ?? 'The query failed.')
      : null);
  const showError = !!errorMessage && !dismissed[activeTabId];
  const canRun = !!activeTab.sql.trim() && !!database && !activeIsInFlight;
  const canClear = activeTab.sql.length > 0 && !activeIsInFlight;
  const canSave = !!activeTab.sql.trim(); // FR-001: disabled only when empty

  return (
    <div className="flex min-w-0 flex-1">
      <SchemaBrowser
        database={database}
        onInsert={(name) => editorRef.current?.insertAtCursor(name)}
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

      <main id="main" className="flex min-w-0 flex-1 flex-col">
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
          className="flex min-w-0 flex-1 flex-col"
        >
        <div className="flex min-h-[52px] flex-none flex-wrap items-center gap-3 border-b border-border bg-surface px-5 py-2">
          <span className="inline-flex h-7 items-center gap-2 rounded-full border border-border bg-surface-2 px-3 text-sm text-text-2">
            <span className="h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
            querying <code className="font-mono text-text">{database}</code>
          </span>
          <div className="flex-1" />
          <Button
            variant="ghost"
            onClick={() => setClearOpen(true)}
            disabled={!canClear}
            aria-label="Clear query"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
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
            aria-label="Save query"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
              <path d="M9 4v5h6" />
              <path d="M8 21v-7h8v7" />
            </svg>
            Save
          </Button>
          {activeIsInFlight ? (
            <Button
              variant="ghost"
              onClick={handleStop}
              aria-label="Stop the running query"
              className="text-danger hover:bg-danger-soft hover:text-danger"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-4 w-4"
                aria-hidden="true"
              >
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              Stop
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={handleRun}
              disabled={!canRun}
              aria-label="Run query"
            >
              <svg
                viewBox="0 0 24 24"
                fill="currentColor"
                stroke="none"
                className="h-4 w-4"
                aria-hidden="true"
              >
                <path d="M7 5v14l11-7z" />
              </svg>
              Run
            </Button>
          )}
        </div>

        <div className="h-[260px] flex-none border-b border-border">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center bg-surface-2 text-sm text-text-3">
                Loading editor&hellip;
              </div>
            }
          >
            <SqlEditor
              ref={editorRef}
              value={activeTab.sql}
              onChange={tabs.setActiveSql}
              onRun={handleRun}
            />
          </Suspense>
        </div>

        {activeExecutionId !== null && (
          <QueryStatusBar
            status={activeStatus}
            isInFlight={activeIsInFlight}
            startedAt={activeRun?.startedAt ?? null}
            rowCount={succeeded ? results.loadedRowCount : undefined}
            hasMoreRows={results.hasMoreServer}
            onDownloadCsv={handleDownloadCsv}
          />
        )}

        {showError && (
          <div className="px-5 pt-4">
            <Banner
              variant="danger"
              title="Query failed."
              onDismiss={() => {
                setRunErrors((e) => ({ ...e, [activeTabId]: null }));
                setDismissed((d) => ({ ...d, [activeTabId]: true }));
              }}
            >
              <code className="font-mono text-xs">{errorMessage}</code>
            </Banner>
          </div>
        )}

        <div className={cx('flex-1 overflow-auto px-5 py-4')}>
          {succeeded ? (
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
              onPrev={results.goPrev}
              onNext={results.goNext}
            />
          ) : (
            <p className="flex h-full items-center justify-center text-sm text-text-3">
              {activeIsInFlight
                ? 'Running your query…'
                : 'Run a query to see results.'}
            </p>
          )}
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
      {dropping && (
        <DropTableDialog
          table={dropping.name}
          isDropping={dropInFlight}
          onConfirm={handleDropConfirm}
          onCancel={() => setDropping(null)}
        />
      )}
      {toast && (
        <Toast
          variant={toast.variant}
          message={toast.message}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  );
}
