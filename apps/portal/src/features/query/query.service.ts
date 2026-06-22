import {
  StartQueryExecutionCommand,
  GetQueryExecutionCommand,
  GetQueryResultsCommand,
  StopQueryExecutionCommand,
} from '@aws-sdk/client-athena';
import { getAthenaClient } from '../../lib/athenaClient';
import { withCredentialRetry } from '../../lib/credentialRetry';
import type { ServiceResult } from '../../types/service.types';
import { DEFAULT_MAX_ROWS } from './query.constants';
import type {
  QueryColumn,
  QueryResultPage,
  QueryState,
  QueryStatus,
} from './query.types';

// The caller's own protected results prefix. The app supplies this OutputLocation
// per query, but it is enforced server-side: IAM (SPEC-032 FR-006) restricts
// writes to `{username}/athenaresults/*` and explicitly DENIES delete there, so a
// query pointed at another user's prefix is denied. The workgroup deliberately
// does not enforce a fixed output location (SPEC-032).
function outputLocation(username: string): string {
  const bucket = import.meta.env.VITE_S3_USER_SPACE_BUCKET as string;
  return `s3://${bucket}/${username}/athenaresults/`;
}

// Athena terminal execution states — polling stops once one is reached (FR-003).
const TERMINAL_STATES: ReadonlySet<QueryState> = new Set([
  'SUCCEEDED',
  'FAILED',
  'CANCELLED',
]);

export function isTerminalState(state: QueryState): boolean {
  return TERMINAL_STATES.has(state);
}

function toServiceError(err: unknown, fallback: string) {
  const e = err as { message?: string; name?: string };
  return {
    success: false as const,
    error: { message: e.message ?? fallback, code: e.name },
  };
}

// FR-002: start an Athena query for the signed-in user. The same path runs both
// `SELECT` and DDL (`CREATE TABLE`, `DROP TABLE`, CTAS, `INSERT`) — it does not
// inspect the query type. Results always land in the caller's own
// `{username}/athenaresults/` prefix (the IAM-enforced isolation boundary).
export async function runQuery(p: {
  sql: string;
  database: string;
  username: string;
}): Promise<ServiceResult<{ queryExecutionId: string }>> {
  const { sql, database, username } = p;
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      const response = await client.send(
        new StartQueryExecutionCommand({
          QueryString: sql,
          WorkGroup: import.meta.env.VITE_ATHENA_WORKGROUP as string,
          QueryExecutionContext: { Database: database },
          ResultConfiguration: { OutputLocation: outputLocation(username) },
        }),
      );
      const queryExecutionId = response.QueryExecutionId;
      if (!queryExecutionId) {
        return {
          success: false,
          error: { message: 'Athena did not return a query execution id' },
        };
      }
      return { success: true, data: { queryExecutionId } };
    } catch (err) {
      return toServiceError(err, 'Failed to start query');
    }
  });
}

// FR-003: fetch a query's current execution status, mapped onto QueryStatus. The
// Athena state strings map 1:1 onto QueryState; a missing status defaults to
// QUEUED (the query was just submitted).
export async function getQueryStatus(
  queryExecutionId: string,
): Promise<ServiceResult<QueryStatus>> {
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      const response = await client.send(
        new GetQueryExecutionCommand({ QueryExecutionId: queryExecutionId }),
      );
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
          outputLocation: exec?.ResultConfiguration?.OutputLocation,
        },
      };
    } catch (err) {
      return toServiceError(err, 'Failed to get query status');
    }
  });
}

// FR-005: cancel a running query. StopQueryExecution transitions the execution to
// CANCELLED, which the FR-003 poller then observes as a terminal state.
export async function stopQuery(
  queryExecutionId: string,
): Promise<ServiceResult<void>> {
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      await client.send(
        new StopQueryExecutionCommand({ QueryExecutionId: queryExecutionId }),
      );
      return { success: true, data: undefined };
    } catch (err) {
      return toServiceError(err, 'Failed to cancel query');
    }
  });
}

// FR-004: read one page of a succeeded query's results. Columns come from
// ResultSetMetadata (name + type); rows are the string cells (Athena returns every
// value as a string). Pagination threads `nextToken`. A DDL/CTAS query that
// produced no result set yields empty columns/rows — not an error.
export async function getQueryResults(p: {
  queryExecutionId: string;
  nextToken?: string;
  maxRows?: number;
}): Promise<ServiceResult<QueryResultPage>> {
  const { queryExecutionId, nextToken, maxRows } = p;
  const pageSize = maxRows ?? DEFAULT_MAX_ROWS;
  // Athena prepends the column names as the first row of the FIRST page of a
  // SELECT (the header foot-gun handled below). Request one extra row on page 1
  // so that, after dropping that header, a SELECT still nets a full `pageSize`
  // data rows; continuation pages have no header and request exactly `pageSize`
  // (SPEC-038 FR-001).
  const isFirstPage = !nextToken;
  return withCredentialRetry(getAthenaClient, async (client) => {
    try {
      const response = await client.send(
        new GetQueryResultsCommand({
          QueryExecutionId: queryExecutionId,
          NextToken: nextToken,
          MaxResults: isFirstPage ? pageSize + 1 : pageSize,
        }),
      );

      const meta = response.ResultSet?.ResultSetMetadata;
      const columns: QueryColumn[] = (meta?.ColumnInfo ?? []).map((c) => ({
        name: c.Name ?? '',
        type: c.Type ?? '',
      }));
      let rows: string[][] = (response.ResultSet?.Rows ?? []).map((r) =>
        (r.Data ?? []).map((d) => d.VarCharValue ?? ''),
      );

      // Athena foot-gun: for `SELECT`, GetQueryResults repeats the column names as
      // the FIRST row of the FIRST page only (never on paged continuations). Drop
      // it when it matches the column metadata. DDL/CTAS return no rows, so this is
      // a no-op there.
      if (!nextToken && rows.length > 0) {
        const first = rows[0];
        const isHeaderRow =
          first.length === columns.length &&
          first.every((value, i) => value === columns[i].name);
        if (isHeaderRow) rows = rows.slice(1);
      }

      return {
        success: true,
        data: { columns, rows, nextToken: response.NextToken },
      };
    } catch (err) {
      return toServiceError(err, 'Failed to fetch query results');
    }
  });
}

// SPEC-044: run a statement and poll it to a terminal state, returning the final
// QueryStatus (success for ANY terminal state — the caller inspects `.state`).
// Used by internal/background runs (View DDL, Drop table) that aren't driven by
// the per-tab UI poller. Never throws.
const STMT_POLL_INTERVAL_MS = 400;
const STMT_MAX_POLLS = 90; // ~36s ceiling for these short statements

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function runStatementToCompletion(p: {
  sql: string;
  database: string;
  username: string;
}): Promise<ServiceResult<QueryStatus>> {
  const started = await runQuery(p);
  if (!started.success) return started;
  const id = started.data.queryExecutionId;

  for (let i = 0; i < STMT_MAX_POLLS; i++) {
    const status = await getQueryStatus(id);
    if (!status.success) return status;
    if (isTerminalState(status.data.state)) return status;
    if (i === STMT_MAX_POLLS - 1) {
      return {
        success: false,
        error: { message: 'Timed out waiting for the query', code: 'Timeout' },
      };
    }
    await delay(STMT_POLL_INTERVAL_MS);
  }
  // Unreachable (the loop returns), but satisfies the type checker.
  return { success: false, error: { message: 'Polling ended unexpectedly' } };
}

// SPEC-044 FR-003 / SPEC-048 FR-006: fetch a table's (or view's) authoritative DDL
// via Athena — `SHOW CREATE VIEW` for a view, `SHOW CREATE TABLE` otherwise —
// assembling the single-column result rows into the statement. Internal UI fetch —
// it does NOT append a query-history entry.
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
    username: p.username,
  });
  if (!done.success) return done;
  if (done.data.state !== 'SUCCEEDED') {
    return {
      success: false,
      error: {
        message: done.data.stateChangeReason ?? `${verb} failed`,
        code: done.data.state,
      },
    };
  }

  // SHOW CREATE TABLE returns one column; each row is a DDL line.
  const results = await getQueryResults({
    queryExecutionId: done.data.queryExecutionId,
    maxRows: 1000,
  });
  if (!results.success) return results;
  const ddl = results.data.rows.map((r) => r[0] ?? '').join('\n');
  return { success: true, data: ddl };
}

// Parse an `s3://bucket/key` URL into its parts; null if it isn't one. Exported
// (SPEC-049) so the Save-results flow can derive the source key from a query's
// `outputLocation` (`s3://{bucket}/{username}/athenaresults/{id}.csv`).
export function parseS3Url(url: string): { bucket: string; key: string } | null {
  const match = /^s3:\/\/([^/]+)\/(.+)$/.exec(url);
  if (!match) return null;
  return { bucket: match[1], key: match[2] };
}
