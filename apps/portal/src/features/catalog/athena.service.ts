import {apiRequest} from '../../lib/apiClient';
import {identifierNeedsQuoting, sqlDdlIdentifier} from '../../lib/sql';
import type {ServiceResult} from '../../types/service.types';
import {DEFAULT_MAX_ROWS} from './catalog.constants';
import {normalizeColumnType} from './catalog.format';
import type {QueryColumn, QueryResultPage, QueryRowCount, QueryState, QueryStatus} from './catalog.types';

// Athena terminal execution states — polling stops once one is reached.
const TERMINAL_STATES: ReadonlySet<QueryState> = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED']);

/** Whether an Athena execution state is terminal — polling stops once reached. */
export function isTerminalState(state: QueryState): boolean {
  return TERMINAL_STATES.has(state);
}

/**
 * Start an Athena query for the signed-in user. The same path runs both
 * `SELECT` and DDL (`CREATE TABLE`, `DROP TABLE`, CTAS, `INSERT`) — it does not inspect
 * the query type.
 *
 * **Three values that used to travel from here are now derived server-side**: the workgroup, the
 * results location and the caller's identity. `username` stays on the signature so no call site
 * changes, and is deliberately NOT sent — the API reads the verified claim, and a username on the
 * wire would be a field the server has to decide whether to trust.
 *
 * @param p - The statement, the caller (unused on the wire) and an optional execution database.
 * @returns The execution id, or the machine code a surface maps to wording.
 */
export async function runQuery(p: {
  sql: string;
  username: string;
  // no execution database context by default — every base table must be
  // fully-qualified `database.table`. `database` is optional and, when omitted (the
  // default), `QueryExecutionContext.Database` is not sent at all.
  database?: string;
}): Promise<ServiceResult<{queryExecutionId: string}>> {
  return apiRequest('athena.start', {
    body: p.database ? {sql: p.sql, database: p.database} : {sql: p.sql}
  });
}

/**
 * Fetch a query's current execution status, mapped onto {@link QueryStatus}.
 *
 * A FAILED or CANCELLED execution is a **success** here, as it always was: the query failing is
 * data about the query, not a failure of the request, and `stateChangeReason` is what the caller
 * turns into wording. The wire says `null` where the domain type says absent.
 *
 * @param queryExecutionId - The execution to poll.
 * @returns The status, or the machine code a surface maps to wording.
 */
export async function getQueryStatus(queryExecutionId: string): Promise<ServiceResult<QueryStatus>> {
  const result = await apiRequest('athena.status', {params: {queryExecutionId}});
  if (!result.success) return result;

  const {state, stateChangeReason, dataScannedBytes, engineExecutionTimeMillis, outputLocation} = result.data;
  return {
    success: true,
    data: {
      queryExecutionId,
      state,
      stateChangeReason: stateChangeReason ?? undefined,
      dataScannedBytes: dataScannedBytes ?? undefined,
      engineExecutionTimeMillis: engineExecutionTimeMillis ?? undefined,
      outputLocation: outputLocation ?? undefined
    }
  };
}

/**
 * Cancel a running query. The execution transitions to `CANCELLED`, which the poller then
 * observes as a terminal state.
 *
 * @param queryExecutionId - The execution to stop.
 * @returns Nothing, or the machine code a surface maps to wording.
 */
export async function stopQuery(queryExecutionId: string): Promise<ServiceResult<void>> {
  const result = await apiRequest('athena.stop', {params: {queryExecutionId}});
  if (!result.success) return result;
  return {success: true, data: undefined};
}

/**
 * Read one page of a succeeded query's results.
 *
 * **The Athena-shaped arithmetic moved to the API** — the first-page `+1` overfetch, the 1000
 * clamp and the repeated-header-row drop are the server's now, and this asks for a page and gets
 * clean columns and rows. What did NOT move is the distinction the page carries: a cell is `null`
 * where Athena reported SQL NULL and `''` where it reported an empty string, and no consumer can
 * reconstruct that if it is flattened.
 *
 * @param p - The execution, an optional continuation token and an optional page size.
 * @returns The page, or the machine code a surface maps to wording.
 */
export async function getQueryResults(p: {
  queryExecutionId: string;
  nextToken?: string;
  maxRows?: number;
}): Promise<ServiceResult<QueryResultPage>> {
  const {queryExecutionId, nextToken, maxRows} = p;
  // Sent explicitly rather than left to the server's own default. The two agree today, and a
  // caller that stops naming its page size would be depending on them continuing to.
  const query: {maxRows: string; nextToken?: string} = {
    maxRows: String(maxRows ?? DEFAULT_MAX_ROWS)
  };
  if (nextToken !== undefined) query.nextToken = nextToken;

  const result = await apiRequest('athena.results', {params: {queryExecutionId}, query});
  if (!result.success) return result;

  const columns: QueryColumn[] = result.data.columns.map((column) => ({
    name: column.name,
    type: normalizeColumnType(column.type)
  }));
  return {
    success: true,
    data: {columns, rows: result.data.rows, nextToken: result.data.nextToken ?? undefined}
  };
}

/**
 * Ask the API for a succeeded execution's total row count, as Athena counted it.
 *
 * One call that scans nothing and ships no row. `rowCount` is a number only for a SELECT whose
 * statistics have landed; `pending` says whether a null is worth asking again for, or means Athena
 * does not count this kind of statement at all.
 *
 * @param queryExecutionId - The succeeded execution.
 * @returns The count, or the machine code a surface maps to wording.
 */
export async function getQueryRowCount(queryExecutionId: string): Promise<ServiceResult<QueryRowCount>> {
  const result = await apiRequest('athena.rowCount', {params: {queryExecutionId}});
  if (!result.success) return result;
  return {success: true, data: {rowCount: result.data.rowCount, pending: result.data.pending}};
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
 *
 * **The loop stays here**, and that is a decision rather than an omission: waiting for a query
 * behind an API would put a multi-minute wait under a 30-second gateway ceiling that cannot be
 * raised. It now polls over API calls instead of SDK calls, and is otherwise untouched.
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

/** One part of a `SHOW CREATE TABLE` name: bare where it parses bare, backticked where it does not. */
function ddlTablePart(name: string): string {
  return identifierNeedsQuoting(name) ? sqlDdlIdentifier(name) : name;
}

/**
 * Fetch a table's (or view's) authoritative DDL via Athena
 * — `SHOW CREATE VIEW` for a view, `SHOW CREATE TABLE` otherwise — assembling
 * the single-column result rows into the statement. Internal UI fetch — it does NOT
 * append a query-history entry.
 *
 * A table name that parses only when quoted — the builder accepts a reserved word such as
 * `order` — is backtick-quoted, `SHOW CREATE TABLE` being Hive DDL; every other name goes bare,
 * as it always has. A view's names stay bare: which engine parses `SHOW CREATE VIEW`, and so
 * which quote it takes, is not something a test here can settle.
 */
export async function getTableDdl(p: {
  database: string;
  table: string;
  username: string;
  isView?: boolean;
}): Promise<ServiceResult<string>> {
  const verb = p.isView ? 'SHOW CREATE VIEW' : 'SHOW CREATE TABLE';
  const done = await runStatementToCompletion({
    sql: p.isView ? `${verb} ${p.database}.${p.table}` : `${verb} ${ddlTablePart(p.database)}.${ddlTablePart(p.table)}`,
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
  // the first page overfetches by one (pageSize + 1) and Athena rejects
  // MaxResults > 1000, so 999 nets a full 1000-row first page — far beyond any
  // real DDL, which is one line per row.
  const results = await getQueryResults({
    queryExecutionId: done.data.queryExecutionId,
    maxRows: 999
  });
  if (!results.success) return results;
  const ddl = results.data.rows.map((r) => r[0] ?? '').join('\n');
  return {success: true, data: ddl};
}
