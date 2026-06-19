import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockedFunction,
} from 'vitest';

vi.mock('../../lib/athenaClient', () => ({ getAthenaClient: vi.fn() }));
vi.mock('../file-browser/fileBrowser.service', () => ({
  getDownloadUrl: vi.fn(),
}));

import { getAthenaClient } from '../../lib/athenaClient';
import { getDownloadUrl } from '../file-browser/fileBrowser.service';
import {
  runQuery,
  getQueryStatus,
  getQueryResults,
  getResultCsvUrl,
  stopQuery,
  isTerminalState,
} from './query.service';

const mockGetClient = getAthenaClient as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockGetDownloadUrl = getDownloadUrl as unknown as MockedFunction<
  (p: { bucket: string; key: string }) => Promise<unknown>
>;

// Athena commands expose their params as `.input`; the fake client records them.
type Sent = { input: Record<string, unknown> };
function clientWithSend(send: (cmd: Sent) => Promise<unknown>) {
  mockGetClient.mockResolvedValue({ success: true, data: { send } });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
  vi.stubEnv('VITE_ATHENA_WORKGROUP', 'test-wg');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('runQuery', () => {
  it('starts the query against the workgroup, database, and per-user output location', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () =>({ QueryExecutionId: 'q-123' }));
    clientWithSend(send);

    const result = await runQuery({
      sql: 'SELECT 1',
      database: 'alice',
      username: 'alice',
    });

    expect(result).toEqual({ success: true, data: { queryExecutionId: 'q-123' } });
    const input = send.mock.calls[0][0].input;
    expect(input.QueryString).toBe('SELECT 1');
    expect(input.WorkGroup).toBe('test-wg');
    expect(input.QueryExecutionContext).toEqual({ Database: 'alice' });
    expect(input.ResultConfiguration).toEqual({
      OutputLocation: 's3://user-bucket/alice/athenaresults/',
    });
  });

  it('does not assume query type — DDL is sent verbatim', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () =>({ QueryExecutionId: 'q-ddl' }));
    clientWithSend(send);

    await runQuery({
      sql: 'CREATE EXTERNAL TABLE t (id int) LOCATION \'s3://user-bucket/alice/t/\'',
      database: 'alice',
      username: 'alice',
    });

    expect(send.mock.calls[0][0].input.QueryString).toMatch(/^CREATE EXTERNAL TABLE/);
  });

  it('errors (no throw) when Athena returns no execution id', async () => {
    clientWithSend(vi.fn(async () => ({})));

    const result = await runQuery({ sql: 'SELECT 1', database: 'alice', username: 'alice' });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.message).toMatch(/execution id/i);
  });

  it('maps a start failure to a ServiceResult error', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('bad sql'), { name: 'InvalidRequestException' });
      }),
    );

    const result = await runQuery({ sql: 'SELEKT 1', database: 'alice', username: 'alice' });

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
          Status: { State: 'SUCCEEDED' },
          Statistics: {
            DataScannedInBytes: 2048,
            EngineExecutionTimeInMillis: 123,
          },
          ResultConfiguration: {
            OutputLocation: 's3://user-bucket/alice/athenaresults/q-1.csv',
          },
        },
      })),
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
        outputLocation: 's3://user-bucket/alice/athenaresults/q-1.csv',
      },
    });
  });

  it('surfaces stateChangeReason on a failed execution', async () => {
    clientWithSend(
      vi.fn(async () => ({
        QueryExecution: {
          Status: { State: 'FAILED', StateChangeReason: 'SYNTAX_ERROR: line 1' },
        },
      })),
    );

    const result = await getQueryStatus('q-2');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.state).toBe('FAILED');
    expect(result.data.stateChangeReason).toBe('SYNTAX_ERROR: line 1');
  });

  it('defaults to QUEUED when no status is present yet', async () => {
    clientWithSend(vi.fn(async () => ({ QueryExecution: {} })));

    const result = await getQueryStatus('q-3');

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.state).toBe('QUEUED');
  });

  it('maps a failure to a ServiceResult error', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('gone'), { name: 'InvalidRequestException' });
      }),
    );

    const result = await getQueryStatus('q-4');

    expect(result.success).toBe(false);
  });
});

describe('stopQuery', () => {
  it('issues StopQueryExecution and returns success', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () =>({}));
    clientWithSend(send);

    const result = await stopQuery('q-5');

    expect(result).toEqual({ success: true, data: undefined });
    expect(send.mock.calls[0][0].input).toEqual({ QueryExecutionId: 'q-5' });
  });

  it('maps a failure to a ServiceResult error (never throws)', async () => {
    clientWithSend(
      vi.fn(async () => {
        throw Object.assign(new Error('nope'), { name: 'InvalidRequestException' });
      }),
    );

    const result = await stopQuery('q-6');

    expect(result.success).toBe(false);
  });
});

describe('getQueryResults', () => {
  it('strips the duplicate header row on the first page and normalizes columns/rows', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () =>({
      ResultSet: {
        ResultSetMetadata: {
          ColumnInfo: [
            { Name: 'id', Type: 'integer' },
            { Name: 'name', Type: 'varchar' },
          ],
        },
        Rows: [
          { Data: [{ VarCharValue: 'id' }, { VarCharValue: 'name' }] }, // header
          { Data: [{ VarCharValue: '1' }, { VarCharValue: 'alice' }] },
          { Data: [{ VarCharValue: '2' }, { VarCharValue: 'bob' }] },
        ],
      },
      NextToken: 'tok2',
    }));
    clientWithSend(send);

    const result = await getQueryResults({ queryExecutionId: 'q-1' });

    expect(result).toEqual({
      success: true,
      data: {
        columns: [
          { name: 'id', type: 'integer' },
          { name: 'name', type: 'varchar' },
        ],
        rows: [
          ['1', 'alice'],
          ['2', 'bob'],
        ],
        nextToken: 'tok2',
      },
    });
  });

  it('requests maxRows + 1 on the first page so a SELECT nets a full page after the header (SPEC-038 FR-001)', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () => ({
      ResultSet: {
        ResultSetMetadata: { ColumnInfo: [{ Name: 'id', Type: 'integer' }] },
        Rows: [],
      },
    }));
    clientWithSend(send);

    await getQueryResults({ queryExecutionId: 'q-1', maxRows: 20 });

    expect(send.mock.calls[0][0].input).toMatchObject({
      QueryExecutionId: 'q-1',
      NextToken: undefined,
      MaxResults: 21,
    });
  });

  it('does not strip a row on a continuation page and threads the token + maxRows', async () => {
    const send = vi.fn<(cmd: Sent) => Promise<unknown>>(async () =>({
      ResultSet: {
        ResultSetMetadata: { ColumnInfo: [{ Name: 'id', Type: 'integer' }] },
        Rows: [{ Data: [{ VarCharValue: '3' }] }],
      },
    }));
    clientWithSend(send);

    const result = await getQueryResults({
      queryExecutionId: 'q-1',
      nextToken: 'tok2',
      maxRows: 20,
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.rows).toEqual([['3']]);
    expect(result.data.nextToken).toBeUndefined();
    expect(send.mock.calls[0][0].input).toMatchObject({
      QueryExecutionId: 'q-1',
      NextToken: 'tok2',
      MaxResults: 20,
    });
  });

  it('returns an empty page (no error) for a DDL query with no result set', async () => {
    clientWithSend(vi.fn(async () => ({})));

    const result = await getQueryResults({ queryExecutionId: 'q-ddl' });

    expect(result).toEqual({
      success: true,
      data: { columns: [], rows: [], nextToken: undefined },
    });
  });
});

describe('getResultCsvUrl', () => {
  it('parses the s3 output location and reuses the SPEC-015 presigner', async () => {
    mockGetDownloadUrl.mockResolvedValueOnce({
      success: true,
      data: { url: 'https://signed', expiresAt: '2026-06-18T10:00:00.000Z' },
    });

    const result = await getResultCsvUrl({
      queryExecutionId: 'q-1',
      outputLocation: 's3://user-bucket/alice/athenaresults/q-1.csv',
    });

    expect(mockGetDownloadUrl).toHaveBeenCalledWith({
      bucket: 'user-bucket',
      key: 'alice/athenaresults/q-1.csv',
    });
    expect(result).toEqual({
      success: true,
      data: { url: 'https://signed', expiresAt: '2026-06-18T10:00:00.000Z' },
    });
  });

  it('errors on an unparseable output location', async () => {
    const result = await getResultCsvUrl({
      queryExecutionId: 'q-1',
      outputLocation: 'not-an-s3-url',
    });

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('InvalidLocation');
    expect(mockGetDownloadUrl).not.toHaveBeenCalled();
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
