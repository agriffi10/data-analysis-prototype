import {
  StartQueryExecutionCommand,
  GetQueryExecutionCommand,
  GetQueryResultsCommand,
  StopQueryExecutionCommand
} from '@aws-sdk/client-athena';
import {getAthenaClient} from '../../lib/athenaClient';
import {withCredentialRetry} from '../../lib/credentialRetry';
import {toServiceError} from '../../lib/serviceResult';
import {userSpaceBucket} from '../../lib/userSpace';
import type {ServiceResult} from '../../types/service.types';
import {DEFAULT_MAX_ROWS} from './catalog.constants';
import {normalizeColumnType} from './catalog.format';
import type {QueryColumn, QueryResultPage, QueryState, QueryStatus} from './catalog.types';

// The caller's own protected results prefix. The app supplies this OutputLocation
// per query, but it is enforced server-side: IAM restricts
// writes to `{username}/athenaresults/*` and explicitly DENIES delete there, so a
// query pointed at another user's prefix is denied. The workgroup deliberately
// does not enforce a fixed output location.
function outputLocation(username: string): string {
  return `s3://${userSpaceBucket()}/${username}/athenaresults/`;
}

// Athena terminal execution states — polling stops once one is reached.
const TERMINAL_STATES: ReadonlySet<QueryState> = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED']);

/** Whether an Athena execution state is terminal — polling stops once reached. */
export function isTerminalState(state: QueryState): boolean {
  return TERMINAL_STATES.has(state);
}

/**
 * Start an Athena query for the signed-in user. The same path runs both
 * `SELECT` and DDL (`CREATE TABLE`, `DROP TABLE`, CTAS, `INSERT`) — it does not inspect
 * the query type. Results always land in the caller's own `{username}/athenaresults/`
 * prefix (the IAM-enforced isolation boundary).
 */
export async function runQuery(p: {
  sql: string;
  username: string;
  // no execution database context by default — every base table must be
  // fully-qualified `database.table`. `database` is optional and, when omitted (the
  // default), `QueryExecutionContext.Database` is not sent at all.
  database?: string;
  // Where results land. Omitted → the personal prefix; a shared
  // path is chosen explicitly at Save time, no longer per run.
  outputLocation?: string;
}): Promise<ServiceResult<{queryExecutionId: string}>> {
  const {sql, database, username, outputLocation: outLoc} = p;
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      const response = await client.send(
        new StartQueryExecutionCommand({
          QueryString: sql,
          WorkGroup: import.meta.env.VITE_ATHENA_WORKGROUP as string,
          // Omit the field entirely when there's no database — Athena then resolves
          // only fully-qualified names, which is the intended behavior.
          ...(database ? {QueryExecutionContext: {Database: database}} : {}),
          ResultConfiguration: {OutputLocation: outLoc ?? outputLocation(username)}
        })
      );
      const queryExecutionId = response.QueryExecutionId;
      if (!queryExecutionId) {
        return {
          success: false,
          // No rule matches this code on purpose — Athena accepting the start call
          // without returning an id is a service fault, and GENERIC is what a user
          // should see. The code exists so the mapper decides that, not a fallthrough.
          error: {message: 'Athena did not return a query execution id', code: 'AthenaNoExecutionId'}
        };
      }
      return {success: true, data: {queryExecutionId}};
    } catch (err) {
      return toServiceError(err, 'Failed to start query');
    }
  });
}

/**
 * Fetch a query's current execution status, mapped onto {@link QueryStatus}.
 * The Athena state strings map 1:1 onto `QueryState`; a missing status defaults to
 * `QUEUED` (the query was just submitted).
 */
export async function getQueryStatus(queryExecutionId: string): Promise<ServiceResult<QueryStatus>> {
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      const response = await client.send(new GetQueryExecutionCommand({QueryExecutionId: queryExecutionId}));
      const exec = response.QueryExecution;
      const state = (exec?.Status?.State ?? 'QUEUED') as QueryState;
      return {
        success: true,
        data: {
          queryExecutionId,
          state,
          stateChangeReason: exec?.Status?.StateChangeReason,
          dataScannedBytes: exec?.Statistics?.DataScannedInBytes,
          engineExecutionTimeMillis: exec?.Statistics?.EngineExecutionTimeInMillis,
          outputLocation: exec?.ResultConfiguration?.OutputLocation
        }
      };
    } catch (err) {
      return toServiceError(err, 'Failed to get query status');
    }
  });
}

/**
 * Cancel a running query. `StopQueryExecution` transitions the execution to
 * `CANCELLED`, which the poller then observes as a terminal state.
 */
export async function stopQuery(queryExecutionId: string): Promise<ServiceResult<void>> {
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      await client.send(new StopQueryExecutionCommand({QueryExecutionId: queryExecutionId}));
      return {success: true, data: undefined};
    } catch (err) {
      return toServiceError(err, 'Failed to cancel query');
    }
  });
}

/**
 * Read one page of a succeeded query's results. Columns come from
 * `ResultSetMetadata` (name + type); rows are the string cells (Athena returns every
 * value as a string). Pagination threads `nextToken`. A DDL/CTAS query that produced no
 * result set yields empty columns/rows — not an error.
 */
export async function getQueryResults(p: {
  queryExecutionId: string;
  nextToken?: string;
  maxRows?: number;
}): Promise<ServiceResult<QueryResultPage>> {
  const {queryExecutionId, nextToken, maxRows} = p;
  const pageSize = maxRows ?? DEFAULT_MAX_ROWS;
  // Athena prepends the column names as the first row of the FIRST page of a
  // SELECT (the header foot-gun handled below). Request one extra row on page 1
  // so that, after dropping that header, a SELECT still nets a full `pageSize`
  // data rows; continuation pages have no header and request exactly `pageSize`.
  // Athena rejects MaxResults > 1000, so at the
  // 1000-row maximum the +1 is clamped away and page 1 nets 999 data rows —
  // callers must not assume uniform page lengths (useQueryResults numbers rows
  // from the actual loaded pages).
  const isFirstPage = !nextToken;
  const ATHENA_MAX_RESULTS = 1000;
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      const response = await client.send(
        new GetQueryResultsCommand({
          QueryExecutionId: queryExecutionId,
          NextToken: nextToken,
          MaxResults: Math.min(isFirstPage ? pageSize + 1 : pageSize, ATHENA_MAX_RESULTS)
        })
      );

      const meta = response.ResultSet?.ResultSetMetadata;
      const columns: QueryColumn[] = (meta?.ColumnInfo ?? []).map((c) => ({
        name: c.Name ?? '',
        type: normalizeColumnType(c.Type ?? '')
      }));
      // An ABSENT `VarCharValue` is SQL NULL; an empty one is an empty string. Collapsing
      // the two to `''` here destroyed the difference for every caller, and no consumer
      // can reconstruct it — the Value panel has to show which one a cell holds.
      let rows: (string | null)[][] = (response.ResultSet?.Rows ?? []).map((r) =>
        (r.Data ?? []).map((d) => d.VarCharValue ?? null)
      );

      // Athena foot-gun: for `SELECT`, GetQueryResults repeats the column names as
      // the FIRST row of the FIRST page only (never on paged continuations). Drop
      // it when it matches the column metadata. DDL/CTAS return no rows, so this is
      // a no-op there.
      if (!nextToken && rows.length > 0) {
        const first = rows[0];
        const isHeaderRow = first.length === columns.length && first.every((value, i) => value === columns[i].name);
        if (isHeaderRow) rows = rows.slice(1);
      }

      return {
        success: true,
        data: {columns, rows, nextToken: response.NextToken}
      };
    } catch (err) {
      return toServiceError(err, 'Failed to fetch query results');
    }
  });
}

const STMT_POLL_INTERVAL_MS = 400;
const STMT_MAX_POLLS = 90; // ~36s ceiling for these short statements

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * The caller stopped waiting — NOT a failure of the statement, which is still running in
 * Athena and will finish.
 *
 * Its own code, deliberately: `'Cancelled'` is already owned by an upload rule whose
 * text is "Upload cancelled.", so reusing it made an abandoned poll announce itself on
 * whatever page the user had navigated to. Callers are expected to recognise
 * {@link isAbandoned} and say NOTHING — there is no one to tell, and nothing went wrong.
 */
export const ABANDONED_CODE = 'Abandoned';

const ABANDONED: ServiceResult<QueryStatus> = {
  success: false,
  error: {message: 'Stopped waiting for the query.', code: ABANDONED_CODE}
};

/** Did this result come back only because the caller stopped waiting? */
export function isAbandoned(result: ServiceResult<unknown>): boolean {
  return !result.success && result.error.code === ABANDONED_CODE;
}

/**
 * Run a statement and poll it to a terminal state, returning the final
 * {@link QueryStatus}. Succeeds for ANY terminal state — the caller inspects
 * `.state`. Used by internal/background runs (View DDL, Drop table) that aren't driven
 * by the per-tab UI poller. Never throws.
 */
export async function runStatementToCompletion(p: {
  sql: string;
  database: string;
  username: string;
  /**
   * Stop polling. Checked before every status call and again after every wait, so a
   * caller that navigates away stops within one interval rather than continuing for
   * the full `STMT_MAX_POLLS` — roughly 36 s of requests nobody is waiting for.
   * The statement itself keeps running in Athena; only this poller gives up.
   */
  signal?: AbortSignal;
}): Promise<ServiceResult<QueryStatus>> {
  const started = await runQuery(p);
  if (!started.success) return started;
  const id = started.data.queryExecutionId;

  for (let i = 0; i < STMT_MAX_POLLS; i++) {
    if (p.signal?.aborted) return ABANDONED;
    const status = await getQueryStatus(id);
    if (!status.success) return status;
    if (isTerminalState(status.data.state)) return status;
    if (i === STMT_MAX_POLLS - 1) {
      return {
        success: false,
        error: {message: 'Timed out waiting for the query', code: 'Timeout'}
      };
    }
    await delay(STMT_POLL_INTERVAL_MS);
    if (p.signal?.aborted) return ABANDONED;
  }
  // Unreachable (the loop returns), but satisfies the type checker.
  return {success: false, error: {message: 'Polling ended unexpectedly', code: 'Timeout'}};
}

/**
 * Fetch a table's (or view's) authoritative DDL via Athena
 * — `SHOW CREATE VIEW` for a view, `SHOW CREATE TABLE` otherwise — assembling
 * the single-column result rows into the statement. Internal UI fetch — it does NOT
 * append a query-history entry.
 */
export async function getTableDdl(p: {
  database: string;
  table: string;
  username: string;
  isView?: boolean;
}): Promise<ServiceResult<string>> {
  const verb = p.isView ? 'SHOW CREATE VIEW' : 'SHOW CREATE TABLE';
  const done = await runStatementToCompletion({
    sql: `${verb} ${p.database}.${p.table}`,
    database: p.database,
    username: p.username
  });
  if (!done.success) return done;
  if (done.data.state !== 'SUCCEEDED') {
    return {
      success: false,
      error: {
        message: done.data.stateChangeReason ?? `${verb} failed`,
        code: done.data.state
      }
    };
  }

  // SHOW CREATE TABLE returns one column; each row is a DDL line. Cap at 999:
  // getQueryResults overfetches by one on the first page (pageSize + 1), and
  // Athena's GetQueryResults rejects MaxResults > 1000. 999 nets a full 1000-row
  // first page — far beyond any real DDL, which is one line per row.
  const results = await getQueryResults({
    queryExecutionId: done.data.queryExecutionId,
    maxRows: 999
  });
  if (!results.success) return results;
  const ddl = results.data.rows.map((r) => r[0] ?? '').join('\n');
  return {success: true, data: ddl};
}
