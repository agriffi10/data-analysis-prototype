import {useCallback, useRef, useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {runQuery, stopQuery} from '../catalog/athena.service';
import {invalidateSchema} from '../catalog/useSchema';
import {TabExecutionPoller} from './TabExecutionPoller';
import {isResultProducingSql, schemaChangingDatabase, statementHint} from './query.sql';
import {logBackgroundFailure, toUserText} from '../../lib/errorMessages';
import type {UseQueryHistoryResult} from './useQueryHistory';
import type {ParsedStatement, QueryTab, ResultTab, RunScope} from './query.types';
import type {QueryStatus} from '../catalog/catalog.types';

// Per-tab in-memory run state (not persisted — results re-fetch on a
// fresh Run). A run is a sequential batch: the statements in
// scope, the in-flight statement's execution, and the result tabs accumulated
// as result-producing statements succeed. `submittedSql` is the CURRENT
// statement's text, kept so the background finalizer can decide whether a
// succeeded DDL should refresh the schema.
export type TabRun = {
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
  savedQuery?: {key: string; name: string};
  /** Submitter-supplied identity, so a caller can tell ITS run from a later one. */
  token?: number;
};

/**
 * Run identity for a caller that must recognise ITS run later (the mobile
 * results view). One object so a token can't be passed without the outcome
 * callback that settles it, or vice versa.
 */
export type RunOwner = {token: number; onOutcome: (started: boolean, error?: string) => void};

export type UseTabRunsResult = {
  /** Per-tab run state, keyed by tab id. Render-time snapshot of `runsRef`. */
  runs: Record<string, TabRun>;
  statuses: Record<string, QueryStatus | undefined>;
  runErrors: Record<string, string | null>;
  dismissed: Record<string, boolean>;
  /** The headless pollers — one per tab holding an execution. Render this; it draws nothing. */
  pollers: React.ReactNode;
  /** Starts a batch in `tabId` (defaults to the active tab). Returns whether the submit began. */
  submitBatch: (statements: ParsedStatement[], scope: RunScope, tabId?: string, owner?: RunOwner) => boolean;
  /** Cancels the active tab's in-flight statement and halts the remainder. */
  handleStop: () => void;
  /** Forgets a closed tab's run state (the execution itself keeps running server-side). */
  dropRunState: (id: string) => void;
  /** Clears a tab's error and marks it dismissed, so the banner stays closed. */
  dismissError: (tabId: string) => void;
  /** switch which result-producing statement the results region shows. */
  selectResultTab: (tabId: string, index: number) => void;
};

type Params = {
  username: string;
  activeTabId: string;
  /** The open tabs — read at submit time for the active tab's saved-query link. */
  tabs: QueryTab[];
  appendEntry: UseQueryHistoryResult['appendEntry'];
  updateEntry: UseQueryHistoryResult['updateEntry'];
};

/**
 * The query workspace's batch state machine, extracted
 * whole from `QueryWorkspace` so the container renders rather than schedules.
 *
 * Owns per-tab run state, the headless pollers that drive it, submission,
 * sequential advancement through a batch, Stop, and the per-tab error/dismissal
 * bookkeeping the banner reads. `runsRef` is the synchronous source of truth —
 * every write goes through `updateRuns`, from event handlers and effects only,
 * never render — so a Stop is visible to an in-flight advancement immediately;
 * state mirrors it for render.
 */
export function useTabRuns({username, activeTabId, tabs, appendEntry, updateEntry}: Params): UseTabRunsResult {
  const queryClient = useQueryClient();

  const [runs, setRuns] = useState<Record<string, TabRun>>({});
  const runsRef = useRef(runs);
  const updateRuns = useCallback((updater: (prev: Record<string, TabRun>) => Record<string, TabRun>) => {
    runsRef.current = updater(runsRef.current);
    setRuns(runsRef.current);
  }, []);
  const [statuses, setStatuses] = useState<Record<string, QueryStatus | undefined>>({});
  const [runErrors, setRunErrors] = useState<Record<string, string | null>>({});
  const [dismissed, setDismissed] = useState<Record<string, boolean>>({});

  // Tabs whose run has been submitted but not yet recorded in `runs`.
  // The de-dupe guard reads this ref so a rapid double-trigger de-dupes before the
  // async setRuns commits, which the runs/statuses render snapshot alone can miss.
  const submittingTabsRef = useRef<Set<string>>(new Set());

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
      }).catch((e) => logBackgroundFailure('query-history', e));

      // a user-typed DDL fully-qualifies its own target; refresh that
      // database's schema (there's no active database to assume).
      const ddlDb = status.state === 'SUCCEEDED' ? schemaChangingDatabase(sql) : null;
      if (ddlDb) void invalidateSchema(queryClient, ddlDb);

      // ── Batch bookkeeping and advancement ────────────────────────────────
      const run = runsRef.current[tabId];
      // Stale finalize (tab closed, or a new run replaced this one) — history
      // above is still recorded; there is no batch to advance.
      if (!run || run.done || run.executionId !== executionId) return;

      // a result-producing statement that succeeded earns a result tab
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

      // Stop at the first non-SUCCEEDED terminal state, and never
      // advance past a Stop even when the statement outran the cancel.
      const hasNext = run.currentIndex < run.statements.length - 1;
      if (status.state !== 'SUCCEEDED' || !hasNext || run.halted) {
        patchRun((cur) => ({
          ...cur,
          done: true,
          ...(status.state === 'FAILED' && {
            // Store friendly text for display; the raw stateChangeReason stays in
            // the QueryStatus/history record for developers.
            failure: {
              statementIndex: cur.currentIndex,
              reason: toUserText({code: status.state, message: status.stateChangeReason})
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
            failure: {statementIndex: next.index, reason: toUserText(started.error)}
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
        // before the poller's finalizer can read-modify-write it.
        await appendEntry({
          queryExecutionId: nextId,
          sql: next.sql,
          database: username,
          submittedAt: new Date().toISOString(),
          ...(run.savedQuery && {
            savedQueryKey: run.savedQuery.key,
            savedQueryName: run.savedQuery.name
          })
        }).catch((e) => logBackgroundFailure('query-history', e));
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
  // sequentially. An explicit tabId lets a just-opened tab
  // (View data) auto-run into itself before the activeTabId state
  // change has committed. A new run replaces the tab's prior run wholesale, so
  // the previous batch's result tabs are cleared. Returns whether the
  // submit began, so a caller that tracks its own run (the mobile results view)
  // doesn't start waiting on a run the guards below refused.
  const submitBatch = (
    statements: ParsedStatement[],
    scope: RunScope,
    tabId: string = activeTabId,
    owner?: RunOwner
  ): boolean => {
    if (statements.length === 0) return false;
    // De-dupe guard. The ref reflects a submit already in flight for this tab even
    // before its `runs` entry commits, so a rapid double-trigger (e.g. View data
    // opens a tab and calls submit in the same tick) starts at most one execution.
    if (submittingTabsRef.current.has(tabId)) return false;
    // Read the ref, not the render snapshot — it reflects a run installed in
    // this same tick (the submittingTabsRef guard is released before re-render).
    const existing = runsRef.current[tabId];
    if (existing && !existing.done) return false;
    submittingTabsRef.current.add(tabId);

    // a run from a tab linked to a saved query records that query in
    // history. Read off the TAB at submit time — the whole link lives there, so
    // there is no list to look the query up in.
    const linkedSaved = tabs.find((t) => t.id === tabId)?.savedQuery;

    setRunErrors((e) => ({...e, [tabId]: null}));
    // An owned submit never writes the tab's error, so it must not un-dismiss one
    // the editor already showed and the user already closed.
    if (!owner) setDismissed((d) => ({...d, [tabId]: false}));
    void (async () => {
      try {
        const first = statements[0];
        // no execution database context — the query fully-qualifies its
        // own tables. Results land in the personal prefix (runQuery's default); a
        // shared destination is chosen explicitly at Save time.
        const result = await runQuery({
          sql: first.sql,
          username
        });
        if (!result.success) {
          const message = toUserText(result.error);
          // An owned submit installs no run when it fails, so nothing would mark
          // the error as that surface's — hand it to the owner instead of the
          // tab, which the editor shell also reads.
          if (owner) owner.onOutcome(false, message);
          else setRunErrors((e) => ({...e, [tabId]: message}));
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
          // Informational only (there's no active database). The
          // personal database is the fixed default context recorded for display.
          database: username,
          submittedAt: new Date().toISOString(),
          ...(linkedSaved && {
            savedQueryKey: linkedSaved.key,
            savedQueryName: linkedSaved.name
          })
        }).catch((e) => logBackgroundFailure('query-history', e));
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
            ...(linkedSaved && {savedQuery: {key: linkedSaved.key, name: linkedSaved.name}}),
            ...(owner && {token: owner.token})
          }
        }));
        owner?.onOutcome(true);
      } catch (e) {
        // Services don't throw by contract, but an unreported submit would leave
        // a caller waiting on an outcome that never comes.
        const message = toUserText(e);
        if (owner) owner.onOutcome(false, message);
        else setRunErrors((err) => ({...err, [tabId]: message}));
      } finally {
        // Hand off to the state-based guard: once `runs[tabId]` commits (success) or
        // the run errored (retryable), the ref no longer needs to block.
        submittingTabsRef.current.delete(tabId);
      }
    })();
    return true;
  };

  // Stop cancels the in-flight statement AND halts the remainder. The
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

  // Drop the closed tab's in-memory run state (its execution keeps running
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

  const dismissError = useCallback((tabId: string) => {
    setRunErrors((e) => ({...e, [tabId]: null}));
    setDismissed((d) => ({...d, [tabId]: true}));
  }, []);

  const selectResultTab = useCallback(
    (tabId: string, index: number) =>
      updateRuns((r) => (r[tabId] ? {...r, [tabId]: {...r[tabId], activeResultTabIndex: index}} : r)),
    [updateRuns]
  );

  // Background pollers — one per tab with an execution, so backgrounded
  // queries finalize concurrently. They render nothing.
  const pollers = Object.entries(runs).map(([tabId, run]) => (
    <TabExecutionPoller
      key={tabId}
      tabId={tabId}
      executionId={run.executionId}
      submittedSql={run.submittedSql}
      onStatus={handleStatus}
      onFinalize={handleFinalize}
    />
  ));

  return {
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
  };
}
