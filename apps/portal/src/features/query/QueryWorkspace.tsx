import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../auth';
import { Button } from '../../components/Button';
import { Banner } from '../../components/Banner';
import { cx } from '../../lib/cx';
import {
  runQuery,
  stopQuery,
  getResultCsvUrl,
  isTerminalState,
} from './query.service';
import { useQueryExecution } from './useQueryExecution';
import { useQueryResults } from './useQueryResults';
import { useQueryHistory } from './useQueryHistory';
import { readQueryDraft, writeQueryDraft, clearQueryDraft } from './queryDraft';
import { ClearQueryDialog } from './ClearQueryDialog';
import { invalidateSchema } from './useSchema';
import { isSchemaChangingSql } from './query.sql';
import { SchemaBrowser } from './SchemaBrowser';
import { QueryStatusBar } from './QueryStatusBar';
import { QueryResultsTable } from './QueryResultsTable';
import { QueryHistoryPanel } from './QueryHistoryPanel';
import type { SqlEditorHandle } from './SqlEditor';
import type { QueryHistoryEntry } from './query.types';

// Monaco is heavy — lazy-load it so it lands in its own async chunk and the Files
// route / landing page never pay for it (SPEC-035 FR-003).
const SqlEditor = lazy(() =>
  import('./SqlEditor').then((m) => ({ default: m.SqlEditor })),
);

const DEFAULT_SQL = `-- Write SQL against your database, then Run (⌘⏎).
SELECT 1;
`;

// SPEC-035 query workspace (FR-002): schema browser (left) + editor/status/results
// (main), wired entirely to the SPEC-034 data layer.
export function QueryWorkspace() {
  const { user } = useAuth();
  const username = user?.username ?? '';
  const database = username;
  const queryClient = useQueryClient();

  // SPEC-040: seed from the per-user sessionStorage draft so an un-run query
  // survives tab switches (remount) and page reloads within the session; fall
  // back to the boilerplate only when there is no draft. Read once at mount.
  const [sql, setSql] = useState(() => readQueryDraft(username) || DEFAULT_SQL);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [errorDismissed, setErrorDismissed] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);

  const editorRef = useRef<SqlEditorHandle>(null);
  const submittedSqlRef = useRef('');
  const finalizedRef = useRef<string | null>(null);

  const { appendEntry, updateEntry } = useQueryHistory(username || null);
  const execution = useQueryExecution(executionId);
  const status = execution.data;
  const isInFlight =
    executionId !== null && (!status || !isTerminalState(status.state));
  const succeeded = status?.state === 'SUCCEEDED';

  // Results only fetch once the query has succeeded. The hook exposes a Prev/Next
  // pager (SPEC-038) — one page (≤20 rows) at a time, not the full result set.
  const results = useQueryResults(succeeded ? executionId : null);

  // SPEC-040: any change to the editor text updates state and persists the draft
  // in one place, so typing, schema-insert, and history re-open all keep the
  // session draft in sync. Clear deliberately bypasses this (it removes the key).
  const applySql = (sqlText: string) => {
    setSql(sqlText);
    writeQueryDraft(username, sqlText);
  };

  // Submit a specific SQL string (shared by Run and history Re-run).
  const submit = (sqlText: string) => {
    if (!sqlText.trim() || !database || isInFlight) return;
    setRunError(null);
    setErrorDismissed(false);
    submittedSqlRef.current = sqlText;
    void (async () => {
      const result = await runQuery({ sql: sqlText, database, username });
      if (!result.success) {
        setRunError(result.error.message);
        return;
      }
      const id = result.data.queryExecutionId;
      finalizedRef.current = null;
      setStartedAt(Date.now());
      setExecutionId(id);
      // Append-at-submit (SPEC-034 FR-007); terminal status filled in below.
      appendEntry({
        queryExecutionId: id,
        sql: sqlText,
        database,
        submittedAt: new Date().toISOString(),
      }).catch((e) => console.warn('[query-history] append failed', e));
    })();
  };

  const handleRun = () => submit(sql);

  const handleStop = () => {
    if (!executionId) return;
    void stopQuery(executionId); // poller observes CANCELLED
  };

  // SPEC-036: re-open loads the entry's SQL into the editor (no auto-run);
  // re-run loads it and submits (a new history entry is appended by submit).
  const handleReopen = (entry: QueryHistoryEntry) => {
    applySql(entry.sql);
    setHistoryOpen(false);
    editorRef.current?.focus();
  };
  const handleRerun = (entry: QueryHistoryEntry) => {
    if (isInFlight) return;
    applySql(entry.sql);
    setHistoryOpen(false);
    submit(entry.sql);
  };

  // Once the execution reaches a terminal state, record its status/stats in
  // history and refresh the schema if a DDL statement succeeded.
  useEffect(() => {
    if (!executionId || !status || !isTerminalState(status.state)) return;
    if (finalizedRef.current === executionId) return;
    finalizedRef.current = executionId;

    updateEntry({
      queryExecutionId: executionId,
      patch: {
        status: status.state,
        dataScannedBytes: status.dataScannedBytes,
        durationMs: status.engineExecutionTimeMillis,
      },
    }).catch((e) => console.warn('[query-history] update failed', e));

    if (
      status.state === 'SUCCEEDED' &&
      database &&
      isSchemaChangingSql(submittedSqlRef.current)
    ) {
      void invalidateSchema(queryClient, database);
    }
  }, [executionId, status, updateEntry, queryClient, database]);

  const handleDownloadCsv = () => {
    if (!executionId || !status?.outputLocation) return;
    void (async () => {
      const result = await getResultCsvUrl({
        queryExecutionId: executionId,
        outputLocation: status.outputLocation as string,
      });
      if (!result.success) {
        setRunError(result.error.message);
        setErrorDismissed(false);
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

  const errorMessage =
    runError ??
    (status?.state === 'FAILED'
      ? (status.stateChangeReason ?? 'The query failed.')
      : null);
  const showError = !!errorMessage && !errorDismissed;
  const canRun = !!sql.trim() && !!database && !isInFlight;
  // SPEC-040 FR-003: Clear is offered only when there is text to clear and no
  // query is executing (don't mutate a running query's context).
  const canClear = sql.length > 0 && !isInFlight;

  // Clear confirms first (no undo), then empties the editor + the persisted
  // draft and refocuses. Cancel is a no-op. Bypasses applySql so the cleared
  // key is not immediately re-written.
  const handleClearConfirm = () => {
    setSql('');
    clearQueryDraft(username);
    setClearOpen(false);
    editorRef.current?.focus();
  };

  return (
    <div className="flex min-w-0 flex-1">
      <SchemaBrowser
        database={database}
        onInsert={(name) => editorRef.current?.insertAtCursor(name)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-[52px] flex-none items-center gap-3 border-b border-border bg-surface px-5">
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
          <Button variant="ghost" onClick={() => setHistoryOpen(true)}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
              <path d="M3 3v5h5" />
              <path d="M12 8v5l3 2" />
            </svg>
            History
          </Button>
          {isInFlight ? (
            <Button
              variant="ghost"
              onClick={handleStop}
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
            <Button variant="primary" onClick={handleRun} disabled={!canRun}>
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
              value={sql}
              onChange={applySql}
              onRun={handleRun}
            />
          </Suspense>
        </div>

        {executionId !== null && (
          <QueryStatusBar
            status={status}
            isInFlight={isInFlight}
            startedAt={startedAt}
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
                setRunError(null);
                setErrorDismissed(true);
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
              {isInFlight ? 'Running your query…' : 'Run a query to see results.'}
            </p>
          )}
        </div>
      </main>

      <QueryHistoryPanel
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        username={username}
        onReopen={handleReopen}
        onRerun={handleRerun}
        rerunDisabled={isInFlight}
      />

      {clearOpen && (
        <ClearQueryDialog
          onConfirm={handleClearConfirm}
          onCancel={() => setClearOpen(false)}
        />
      )}
    </div>
  );
}
