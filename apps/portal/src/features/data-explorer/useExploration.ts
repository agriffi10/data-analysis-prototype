import {useEffect, useMemo, useRef} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {isTerminalState, runQuery} from '../catalog/athena.service';
import {useQueryExecution} from '../catalog/useQueryExecution';
import {apiRetryPolicy} from '../../lib/apiClient';
import {unwrap} from '../../lib/serviceResult';
import {NO_KEY} from '../../lib/queryKeys';
import {explorerKeys, explorationSourceScope} from './explorerKeys';
import {renderExplorationSql} from './renderExplorationSql';
import type {QueryState} from '../catalog/catalog.types';
import type {ExecutionCost, Exploration} from './dataExplorer.types';

export type UseExplorationResult = {
  /** The rendered statement, or null when there is no exploration / it could not render. */
  sql: string | null;
  queryExecutionId: string | null;
  state: QueryState | null;
  /**
   * Where Athena wrote this execution's CSV, once it has SUCCEEDED.
   *
   * The whole of export: a server-side `CopyObject` of that object captures every row the
   * statement returned, filters, ordering and grouping included, without a second query and
   * without a second bill. Present only on a succeeded execution, which is what makes the
   * export refusal a question about this field rather than about the grid.
   */
  outputLocation: string | undefined;
  /** What this execution scanned. Null until the execution reports it. */
  cost: ExecutionCost | null;
  /** The statement is starting or still running, with no verdict that its watch outlived the ceiling. */
  isPending: boolean;
  /**
   * A render refusal, a failed StartQueryExecution, a failed poll, or the verdict that the watch
   * outlived its ceiling (`isQueryStillRunning`). Render via `toUserMessage`.
   */
  error: unknown;
};

/**
 * Runs an exploration and reports what it cost.
 *
 * The rendered SQL is the cache key, so this hook is the feature's cost control as much
 * as its data path: an identical description resolves to the execution already run.
 * Paging is NOT here — the caller pages the returned execution id through the catalog's
 * `useQueryResults`, whose `NextToken` walk scans no additional bytes.
 *
 * @param exploration - The exploration to run, or null to run nothing.
 * @returns The rendered SQL, the execution, its state, its cost, and any failure.
 */
export function useExploration(exploration: Exploration | null): UseExplorationResult {
  const {user} = useAuth();
  const username = user?.username ?? '';
  const queryClient = useQueryClient();

  // A description that cannot render is a caller bug, but it must not take the page down
  // with it — it surfaces as an error like any other, and no query is started.
  const rendered = useMemo((): {sql: string; error: null} | {sql: null; error: unknown} => {
    if (!exploration) return {sql: null, error: null};
    try {
      return {sql: renderExplorationSql(exploration.source, exploration.query), error: null};
    } catch (error) {
      return {sql: null, error};
    }
  }, [exploration]);

  const sql = rendered.sql;

  // The source segments the key is filed under. A stable placeholder while there is nothing
  // to run, for the same reason the SQL has one: the hook order must not depend on it.
  const scope = useMemo(
    () => (exploration ? explorationSourceScope(exploration.source) : ([NO_KEY, NO_KEY, NO_KEY] as const)),
    [exploration]
  );

  const enabled = sql !== null && username !== '';

  const start = useQuery({
    // A stable placeholder keeps the hook order constant while disabled.
    queryKey: explorerKeys.execution(scope, sql ?? NO_KEY),
    enabled,
    // The execution id is durable for the session: re-running an identical statement
    // would scan the same bytes for the same rows, so the cached id IS the right answer.
    //
    // `gcTime` is as load-bearing as `staleTime` and is the half that is easy to omit.
    // Changing a filter detaches the previous statement's observer, and under TanStack's
    // 5-minute default its entry is then collected — so the "changing a filter
    // and changing it back is a cache hit" would hold for five minutes and silently
    // become a second execution, and a second bill, after that. An exploration session
    // lasts longer than five minutes; the cache is a few dozen strings.
    staleTime: Infinity,
    gcTime: Infinity,
    // Idempotency is the ROUTE's property, not this hook's. Omitted, this inherits the app's
    // own default of `retry: 1`, so a failing apply issued two `StartQueryExecution` calls about a
    // second apart — two executions, two bills, for one gesture — on the strength of it looking
    // like a read. The contract says starting a query is not one.
    retry: apiRetryPolicy('athena.start'),
    queryFn: async (): Promise<string> => {
      const result = await runQuery({sql: sql as string, username});
      return unwrap(result).queryExecutionId;
    }
  });

  const queryExecutionId = start.data ?? null;
  const poll = useQueryExecution(queryExecutionId);
  const status = poll.status ?? null;
  const state = status?.state ?? null;

  // What the poll last said about THIS statement, read by the cleanup below. A ref rather
  // than state: nothing renders from it, and it must survive the render in which `sql`
  // changes so the cleanup can still see the outgoing statement's verdict.
  const lastVerdict = useRef<{sql: string; state: QueryState} | null>(null);
  useEffect(() => {
    if (sql !== null && state !== null) lastVerdict.current = {sql, state};
  }, [sql, state]);

  // a failed execution must not be cached as a success — re-applying the same
  // description retries. The eviction happens on the way OUT (the statement changed, or
  // the hook unmounted), never while mounted: evicting on FAILED with an observer
  // attached refetches immediately, which is start → FAILED → evict → start, an unbounded
  // loop against StartQueryExecution on any permanently-bad statement.
  //
  // AWS does not bill a FAILED query, so the loop's first cost is the API hammering and
  // the account-wide concurrency it consumes. It is not only that: this branch also covers
  // CANCELLED, and a cancelled query IS billed for what it scanned before it stopped — so
  // a loop over a statement the user keeps stopping bills every pass.
  useEffect(() => {
    if (sql === null) return;
    return () => {
      const verdict = lastVerdict.current;
      if (verdict?.sql === sql && (verdict.state === 'FAILED' || verdict.state === 'CANCELLED')) {
        queryClient.removeQueries({queryKey: explorerKeys.execution(scope, sql)});
      }
    };
  }, [sql, scope, queryClient]);

  const cost = useMemo((): ExecutionCost | null => {
    // TERMINAL states only. A QUEUED or RUNNING poll carries no `Statistics`, so it reports
    // a perfectly confident 0 B — and a consumer that captures the FIRST cost it sees for an
    // execution (the per-apply figure does, deliberately, so that a cache hit is
    // detected before the ledger is written) would then freeze that 0 forever. Every real
    // query takes more than one poll, so the surface said "This query scanned 0 B" beside a
    // running total that disagreed with it.
    if (!status || !isTerminalState(status.state)) return null;
    // an execution that fails before reporting statistics contributes ZERO,
    // never NaN — a NaN here propagates silently into the tab's cumulative total and
    // renders as "NaN B" long after the failed run is forgotten.
    return {
      bytesScanned: status.dataScannedBytes ?? 0,
      engineMillis: status.engineExecutionTimeMillis ?? 0
    };
  }, [status]);

  // A query Athena REFUSES is not an error anywhere in the plumbing: `getQueryStatus`
  // resolves, and the reason arrives as a field on a successful poll. So the state has to
  // be turned into one here, in the shape `toUserMessage` maps engine text from — a syntax
  // error in the expression bar is a `stateChangeReason` and nothing
  // else. Without this the failure surfaced one layer later as "could not read results",
  // which is a true sentence about the wrong thing.
  const executionFailure = useMemo(() => {
    if (!status || (status.state !== 'FAILED' && status.state !== 'CANCELLED')) return null;
    return {code: status.state, message: status.stateChangeReason};
  }, [status]);

  return {
    sql,
    queryExecutionId,
    state,
    // Taken from the poll rather than rebuilt from the execution id: the results location
    // is the workgroup's business, and a second builder here would be a second thing to be
    // wrong about a bucket this feature never names.
    outputLocation: status?.state === 'SUCCEEDED' ? status.outputLocation : undefined,
    cost,
    // A disabled query reports `isPending` forever in TanStack v5, so `enabled` gates it:
    // signed out with no username, nothing is in flight and a permanent spinner is a lie.
    // A statement the watch gave up on is not pending: nothing more will be asked about it.
    isPending:
      enabled &&
      (start.isPending ||
        start.isFetching ||
        (state !== null && !isTerminalState(state) && poll.stillRunning === null)),
    error: rendered.error ?? start.error ?? poll.error ?? executionFailure ?? poll.stillRunning ?? null
  };
}
