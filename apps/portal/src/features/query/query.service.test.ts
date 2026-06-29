import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/athenaClient', () => ({getAthenaClient: vi.fn()}));

import {getAthenaClient} from '../../lib/athenaClient';
import {
  runQuery,
  getQueryStatus,
  getQueryResults,
  parseS3Url,
  getTableDdl,
  runStatementToCompletion,
  resultOutputLocation,
  stopQuery,
  isTerminalState
} from './query.service';
import type {Connection} from './query.types';

const mockGetClient = getAthenaClient as unknown as MockedFunction<() => Promise<unknown>>;

// Athena commands expose their params as `.input`; the fake client records them.
type Sent = {input: Record<string, unknown>};
function clientWithSend(send: (cmd: Sent) => Promise<unknown>) {
  mockGetClient.mockResolvedValue({success: true, data: {send}});
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');
  vi.stubEnv('VITE_ATHENA_WORKGROUP', 'test-wg');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('runQuery', () => {
  it('starts the query against the workgroup, database, and per-user output location', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({QueryExecutionId: 'q-123'}));
    clientWithSend(send);

    const result = await runQuery({
      sql: 'SELECT 1',
      database: 'alice',
      username: 'alice'
    });

    expect(result).toEqual({success: true, data: {queryExecutionId: 'q-123'}});
    const input = send.mock.calls[0][0].input;
    expect(input.QueryString).toBe('SELECT 1');
    expect(input.WorkGroup).toBe('test-wg');
    expect(input.QueryExecutionContext).toEqual({Database: 'alice'});
    expect(input.ResultConfiguration).toEqual({
      OutputLocation: 's3://user-bucket/alice/athenaresults/'
    });
  });

  it('honors an explicit outputLocation (SPEC-055 shared routing)', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({QueryExecutionId: 'q-shared'}));
    clientWithSend(send);

    await runQuery({
      sql: 'SELECT 1',
      database: 'salesdata',
      username: 'alice',
      outputLocation: 's3://shared-bucket/salesdata/athenaresults/alice/'
    });

    expect(send.mock.calls[0][0].input.ResultConfiguration).toEqual({
      OutputLocation: 's3://shared-bucket/salesdata/athenaresults/alice/'
    });
    expect(send.mock.calls[0][0].input.QueryExecutionContext).toEqual({Database: 'salesdata'});
  });

  it('does not assume query type — DDL is sent verbatim', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({QueryExecutionId: 'q-ddl'}));
    clientWithSend(send);

    await runQuery({
      sql: "CREATE EXTERNAL TABLE t (id int) LOCATION 's3://user-bucket/alice/t/'",
      database: 'alice',
      username: 'alice'
    });

    expect(send.mock.calls[0][0].input.QueryString).toMatch(/^CREATE EXTERNAL TABLE/);
  });

  it('errors (no throw) when Athena returns no execution id', async () => {
    clientWithSend(vi.fn(async () => ({})));

    const result = await runQuery({sql: 'SELECT 1', database: 'alice', username: 'alice'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/execution id/i);
  });

  it('maps a start failure to a ServiceResult error', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('bad sql'), {name: 'InvalidRequestException'});
      })
    );

    const result = await runQuery({sql: 'SELEKT 1', database: 'alice', username: 'alice'});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('bad sql');
    expect(result.error.code).toBe('InvalidRequestException');
  });
});

describe('getQueryStatus', () => {
  it('maps a succeeded execution onto QueryStatus', async () => {
    clientWithSend(
      vi.fn(async () => ({
        QueryExecution: {
          Status: {State: 'SUCCEEDED'},
          Statistics: {
            DataScannedInBytes: 2048,
            EngineExecutionTimeInMillis: 123
          },
          ResultConfiguration: {
            OutputLocation: 's3://user-bucket/alice/athenaresults/q-1.csv'
          }
        }
      }))
    );

    const result = await getQueryStatus('q-1');

    expect(result).toEqual({
      success: true,
      data: {
        queryExecutionId: 'q-1',
        state: 'SUCCEEDED',
        stateChangeReason: undefined,
        dataScannedBytes: 2048,
        engineExecutionTimeMillis: 123,
        outputLocation: 's3://user-bucket/alice/athenaresults/q-1.csv'
      }
    });
  });

  it('surfaces stateChangeReason on a failed execution', async () => {
    clientWithSend(
      vi.fn(async () => ({
        QueryExecution: {
          Status: {State: 'FAILED', StateChangeReason: 'SYNTAX_ERROR: line 1'}
        }
      }))
    );

    const result = await getQueryStatus('q-2');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.state).toBe('FAILED');
    expect(result.data.stateChangeReason).toBe('SYNTAX_ERROR: line 1');
  });

  it('defaults to QUEUED when no status is present yet', async () => {
    clientWithSend(vi.fn(async () => ({QueryExecution: {}})));

    const result = await getQueryStatus('q-3');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.state).toBe('QUEUED');
  });

  it('maps a failure to a ServiceResult error', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('gone'), {name: 'InvalidRequestException'});
      })
    );

    const result = await getQueryStatus('q-4');

    expect(result.success).toBe(false);
  });
});

describe('stopQuery', () => {
  it('issues StopQueryExecution and returns success', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({}));
    clientWithSend(send);

    const result = await stopQuery('q-5');

    expect(result).toEqual({success: true, data: undefined});
    expect(send.mock.calls[0][0].input).toEqual({QueryExecutionId: 'q-5'});
  });

  it('maps a failure to a ServiceResult error (never throws)', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('nope'), {name: 'InvalidRequestException'});
      })
    );

    const result = await stopQuery('q-6');

    expect(result.success).toBe(false);
  });
});

describe('getQueryResults', () => {
  it('strips the duplicate header row on the first page and normalizes columns/rows', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({
      ResultSet: {
        ResultSetMetadata: {
          ColumnInfo: [
            {Name: 'id', Type: 'integer'},
            {Name: 'name', Type: 'varchar'}
          ]
        },
        Rows: [
          {Data: [{VarCharValue: 'id'}, {VarCharValue: 'name'}]}, // header
          {Data: [{VarCharValue: '1'}, {VarCharValue: 'alice'}]},
          {Data: [{VarCharValue: '2'}, {VarCharValue: 'bob'}]}
        ]
      },
      NextToken: 'tok2'
    }));
    clientWithSend(send);

    const result = await getQueryResults({queryExecutionId: 'q-1'});

    expect(result).toEqual({
      success: true,
      data: {
        columns: [
          {name: 'id', type: 'integer'},
          {name: 'name', type: 'varchar'}
        ],
        rows: [
          ['1', 'alice'],
          ['2', 'bob']
        ],
        nextToken: 'tok2'
      }
    });
  });

  it('requests maxRows + 1 on the first page so a SELECT nets a full page after the header (SPEC-038 FR-001)', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({
      ResultSet: {
        ResultSetMetadata: {ColumnInfo: [{Name: 'id', Type: 'integer'}]},
        Rows: []
      }
    }));
    clientWithSend(send);

    await getQueryResults({queryExecutionId: 'q-1', maxRows: 20});

    expect(send.mock.calls[0][0].input).toMatchObject({
      QueryExecutionId: 'q-1',
      NextToken: undefined,
      MaxResults: 21
    });
  });

  it('does not strip a row on a continuation page and threads the token + maxRows', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({
      ResultSet: {
        ResultSetMetadata: {ColumnInfo: [{Name: 'id', Type: 'integer'}]},
        Rows: [{Data: [{VarCharValue: '3'}]}]
      }
    }));
    clientWithSend(send);

    const result = await getQueryResults({
      queryExecutionId: 'q-1',
      nextToken: 'tok2',
      maxRows: 20
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.rows).toEqual([['3']]);
    expect(result.data.nextToken).toBeUndefined();
    expect(send.mock.calls[0][0].input).toMatchObject({
      QueryExecutionId: 'q-1',
      NextToken: 'tok2',
      MaxResults: 20
    });
  });

  it('returns an empty page (no error) for a DDL query with no result set', async () => {
    clientWithSend(vi.fn(async () => ({})));

    const result = await getQueryResults({queryExecutionId: 'q-ddl'});

    expect(result).toEqual({
      success: true,
      data: {columns: [], rows: [], nextToken: undefined}
    });
  });
});

describe('parseS3Url (SPEC-049)', () => {
  it('splits an s3:// URL into bucket + key', () => {
    expect(parseS3Url('s3://user-bucket/alice/athenaresults/q-1.csv')).toEqual({
      bucket: 'user-bucket',
      key: 'alice/athenaresults/q-1.csv'
    });
  });

  it('returns null for a non-s3 URL', () => {
    expect(parseS3Url('not-an-s3-url')).toBeNull();
  });
});

describe('resultOutputLocation (SPEC-055)', () => {
  const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
  const shared: Connection = {
    id: 'salesdata',
    label: 'salesdata',
    database: 'salesdata',
    kind: 'shared',
    status: 'active',
    role: 'member'
  };

  it('routes a personal connection to the user-space prefix', () => {
    expect(resultOutputLocation(personal, 'alice')).toBe('s3://user-bucket/alice/athenaresults/');
  });

  it('routes a shared connection to {shared-bucket}/{name}/athenaresults/{username}/', () => {
    expect(resultOutputLocation(shared, 'alice')).toBe('s3://shared-bucket/salesdata/athenaresults/alice/');
  });
});

describe('isTerminalState', () => {
  it('is true for terminal states and false otherwise', () => {
    expect(isTerminalState('SUCCEEDED')).toBe(true);
    expect(isTerminalState('FAILED')).toBe(true);
    expect(isTerminalState('CANCELLED')).toBe(true);
    expect(isTerminalState('QUEUED')).toBe(false);
    expect(isTerminalState('RUNNING')).toBe(false);
  });
});

// SPEC-044: a stateful Athena fake dispatching by command class name. `statuses`
// is consumed one GetQueryExecution call at a time (terminal-first needs one).
function athenaFake(opts: {
  startId?: string;
  statuses: string[];
  resultRows?: string[][];
  resultColumns?: {Name: string; Type: string}[];
}) {
  const statuses = [...opts.statuses];
  const send = vi.fn(async (cmd: {constructor: {name: string}; input: Record<string, unknown>}) => {
    switch (cmd.constructor.name) {
      case 'StartQueryExecutionCommand':
        return {QueryExecutionId: opts.startId ?? 'q-1'};
      case 'GetQueryExecutionCommand': {
        const state = statuses.shift() ?? 'SUCCEEDED';
        return {
          QueryExecution: {
            Status: {State: state, StateChangeReason: state === 'FAILED' ? 'boom' : undefined},
            Statistics: {DataScannedInBytes: 10, EngineExecutionTimeInMillis: 20}
          }
        };
      }
      case 'GetQueryResultsCommand':
        return {
          ResultSet: {
            ResultSetMetadata: {
              ColumnInfo: opts.resultColumns ?? [{Name: 'createtab_stmt', Type: 'varchar'}]
            },
            Rows: (opts.resultRows ?? []).map((r) => ({
              Data: r.map((v) => ({VarCharValue: v}))
            }))
          }
        };
      default:
        return {};
    }
  });
  clientWithSend(send);
  return send;
}

describe('runStatementToCompletion', () => {
  it('runs and polls to a terminal state, returning the final status', async () => {
    athenaFake({statuses: ['SUCCEEDED']});
    const result = await runStatementToCompletion({
      sql: 'DROP TABLE alice.foo',
      database: 'alice',
      username: 'alice'
    });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.state).toBe('SUCCEEDED');
    expect(result.data.queryExecutionId).toBe('q-1');
  });
});

describe('getTableDdl', () => {
  it('runs SHOW CREATE TABLE and joins the result rows into the DDL', async () => {
    const send = athenaFake({
      statuses: ['SUCCEEDED'],
      resultRows: [['CREATE EXTERNAL TABLE foo ('], ['  id bigint'], [')']]
    });
    const result = await getTableDdl({
      database: 'alice',
      table: 'foo',
      username: 'alice'
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toBe('CREATE EXTERNAL TABLE foo (\n  id bigint\n)');
    // It issued SHOW CREATE TABLE for the table.
    const start = send.mock.calls.find((c) => c[0].constructor.name === 'StartQueryExecutionCommand');
    expect(start?.[0].input.QueryString).toBe('SHOW CREATE TABLE alice.foo');
  });

  it('returns an error when the statement does not succeed', async () => {
    athenaFake({statuses: ['FAILED']});
    const result = await getTableDdl({
      database: 'alice',
      table: 'foo',
      username: 'alice'
    });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toBe('boom');
  });

  it('requests at most MaxResults 1000 for the DDL fetch (Athena hard cap)', async () => {
    const send = athenaFake({
      statuses: ['SUCCEEDED'],
      resultRows: [['CREATE EXTERNAL TABLE foo (']]
    });
    const result = await getTableDdl({
      database: 'alice',
      table: 'foo',
      username: 'alice'
    });
    expect(result.success).toBe(true);
    // getQueryResults overfetches by one on the first page, so a maxRows of 1000
    // would request MaxResults 1001 and Athena rejects it. Assert we stay <= 1000.
    const getResults = send.mock.calls.find((c) => c[0].constructor.name === 'GetQueryResultsCommand');
    expect(getResults?.[0].input.MaxResults).toBeLessThanOrEqual(1000);
  });

  it('runs SHOW CREATE VIEW for a view (SPEC-048)', async () => {
    const send = athenaFake({
      statuses: ['SUCCEEDED'],
      resultRows: [['CREATE VIEW foo AS'], ['SELECT 1']]
    });
    const result = await getTableDdl({
      database: 'alice',
      table: 'foo',
      username: 'alice',
      isView: true
    });
    expect(result.success).toBe(true);
    const start = send.mock.calls.find((c) => c[0].constructor.name === 'StartQueryExecutionCommand');
    expect(start?.[0].input.QueryString).toBe('SHOW CREATE VIEW alice.foo');
  });
});
