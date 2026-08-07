import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import type {MockedFunction} from 'vitest';
import {getGlueClient} from '../../lib/glueClient';
import {getDatabase, listTables} from './glue.service';
import {getAthenaClient} from '../../lib/athenaClient';
import {
  ABANDONED_CODE,
  getQueryResults,
  getQueryStatus,
  getTableDdl,
  isAbandoned,
  isTerminalState,
  runQuery,
  runStatementToCompletion,
  stopQuery
} from './query.service';
import {getS3Client} from '../../lib/s3Client';
import {appendQueryHistory, getQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
import {getSavedQueries, removeSavedQuery, upsertSavedQuery} from './savedQueries.service';
import type {QueryHistory, QueryHistoryEntry, SavedQueriesStore, SavedQuery} from './query.types';

// ─── from glue.service.test.ts ───
vi.mock('../../lib/glueClient', () => ({getGlueClient: vi.fn()}));

vi.mock('../../lib/athenaClient', () => ({getAthenaClient: vi.fn()}));
vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

describe('glue.service', () => {
  const mockGetClient = getGlueClient as unknown as MockedFunction<() => Promise<unknown>>;

  type Sent = {input: Record<string, unknown>};
  function clientWithSend(send: (cmd: Sent) => Promise<unknown>) {
    mockGetClient.mockResolvedValue({success: true, data: {send}});
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getDatabase', () => {
    it('returns the database name when it exists', async () => {
      clientWithSend(vi.fn(async () => ({Database: {Name: 'alice'}})));

      const result = await getDatabase('alice');

      expect(result).toEqual({success: true, data: {name: 'alice'}});
    });

    it('maps EntityNotFoundException to a clean NotFound error', async () => {
      clientWithSend(
        vi.fn(async () => {
          throw Object.assign(new Error('missing'), {
            name: 'EntityNotFoundException'
          });
        })
      );

      const result = await getDatabase('alice');

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('NotFound');
    });
  });

  describe('listTables', () => {
    it('normalizes tables + columns and paginates past the page cap', async () => {
      const send = vi
        .fn<(cmd: Sent) => Promise<unknown>>()
        .mockResolvedValueOnce({
          TableList: [
            {
              Name: 'events',
              TableType: 'EXTERNAL_TABLE',
              StorageDescriptor: {
                Location: 's3://user-bucket/alice/events/',
                Columns: [
                  {Name: 'id', Type: 'bigint'},
                  {Name: 'ts', Type: 'timestamp'}
                ]
              }
            }
          ],
          NextToken: 'page2'
        })
        .mockResolvedValueOnce({
          TableList: [{Name: 'lookup', StorageDescriptor: {Columns: []}}]
        });
      clientWithSend(send);

      const result = await listTables('alice');

      expect(send).toHaveBeenCalledTimes(2);
      expect(send.mock.calls[1][0].input).toMatchObject({NextToken: 'page2'});
      expect(result).toEqual({
        success: true,
        data: [
          {
            name: 'events',
            tableType: 'EXTERNAL_TABLE',
            location: 's3://user-bucket/alice/events/',
            columns: [
              {name: 'id', type: 'bigint'},
              {name: 'ts', type: 'timestamp'}
            ]
          },
          {name: 'lookup', tableType: undefined, location: undefined, columns: []}
        ]
      });
    });

    it('treats a not-yet-created database as an empty schema (not an error)', async () => {
      clientWithSend(
        vi.fn(async () => {
          throw Object.assign(new Error('no db'), {
            name: 'EntityNotFoundException'
          });
        })
      );

      const result = await listTables('alice');

      expect(result).toEqual({success: true, data: []});
    });

    it('maps AccessDenied to a clean error', async () => {
      clientWithSend(
        vi.fn(async () => {
          throw Object.assign(new Error('denied'), {
            name: 'AccessDeniedException'
          });
        })
      );

      const result = await listTables('bob');

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('AccessDeniedException');
    });
  });
});

// ─── from query.service.test.ts ───

describe('query.service', () => {
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
          // Athena's Presto engine names (`integer`, `varchar`) are mapped to the
          // Glue/Hive DDL names (`int`, `string`) the schema rail shows.
          columns: [
            {name: 'id', type: 'int'},
            {name: 'name', type: 'string'}
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

  describe('isTerminalState', () => {
    it('is true for terminal states and false otherwise', () => {
      expect(isTerminalState('SUCCEEDED')).toBe(true);
      expect(isTerminalState('FAILED')).toBe(true);
      expect(isTerminalState('CANCELLED')).toBe(true);
      expect(isTerminalState('QUEUED')).toBe(false);
      expect(isTerminalState('RUNNING')).toBe(false);
    });
  });

  // A stateful Athena fake dispatching by command class name. `statuses` is
  // consumed one GetQueryExecution call at a time (terminal-first needs one).
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

  describe('runStatementToCompletion honours an AbortSignal (SPEC-155 FR-006)', () => {
    it('stops polling when the caller has navigated away', async () => {
      // Without this the poller kept asking for ~36 s after the workspace unmounted.
      let calls = 0;
      clientWithSend(async () => {
        calls += 1;
        return calls === 1 ? {QueryExecutionId: 'q-abandon'} : {QueryExecution: {Status: {State: 'RUNNING'}}};
      });

      const controller = new AbortController();
      const pending = runStatementToCompletion({
        sql: 'DROP TABLE alice.t',
        database: 'alice',
        username: 'alice',
        signal: controller.signal
      });
      controller.abort();

      const result = await pending;
      expect(result.success).toBe(false);
      if (result.success) return;
      // Its OWN code, not 'Cancelled' — that one is owned by an upload rule whose text is
      // "Upload cancelled.", which an abandoned poll would then have announced to a user
      // who had simply navigated away.
      expect(result.error.code).toBe(ABANDONED_CODE);
      expect(isAbandoned(result)).toBe(true);
    });

    it('polls normally when no signal is given', async () => {
      let calls = 0;
      clientWithSend(async () => {
        calls += 1;
        return calls === 1 ? {QueryExecutionId: 'q-ok'} : {QueryExecution: {Status: {State: 'SUCCEEDED'}}};
      });

      const result = await runStatementToCompletion({sql: 'DROP TABLE alice.t', database: 'alice', username: 'alice'});
      expect(result.success).toBe(true);
    });
  });
});

// ─── from queryHistory.service.test.ts ───

describe('queryHistory.service', () => {
  const mockGetClient = getS3Client as unknown as MockedFunction<() => Promise<unknown>>;

  // A stateful fake user-space bucket: GetObject reads the stored JSON (or throws
  // NoSuchKey when absent); PutObject (input has a Body) overwrites it.
  function fakeBucket(initial: string | null) {
    let stored = initial;
    const send = vi.fn(async (cmd: {input: {Body?: string}}) => {
      if (cmd.input.Body !== undefined) {
        stored = cmd.input.Body;
        return {};
      }
      if (stored === null) {
        throw Object.assign(new Error('missing'), {name: 'NoSuchKey'});
      }
      const body = stored;
      return {Body: {transformToString: async () => body}};
    });
    mockGetClient.mockResolvedValue({success: true, data: {send}});
    return {send, stored: () => stored};
  }

  function entry(id: string): QueryHistoryEntry {
    return {
      queryExecutionId: id,
      sql: 'SELECT 1',
      database: 'alice',
      submittedAt: '2026-06-18T10:00:00.000Z'
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('getQueryHistory', () => {
    it('returns an empty history (no error) when the file is absent', async () => {
      fakeBucket(null);

      const result = await getQueryHistory('alice');

      expect(result).toEqual({success: true, data: {version: 1, entries: []}});
    });

    it('reads and parses an existing history file', async () => {
      fakeBucket(JSON.stringify({version: 1, entries: [entry('q1')]} as QueryHistory));

      const result = await getQueryHistory('alice');

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries).toHaveLength(1);
      expect(result.data.entries[0].queryExecutionId).toBe('q1');
    });

    it('falls back to empty on a malformed file', async () => {
      fakeBucket('not json{');

      const result = await getQueryHistory('alice');

      expect(result).toEqual({success: true, data: {version: 1, entries: []}});
    });
  });

  describe('appendQueryHistory', () => {
    it('prepends newest-first and writes back', async () => {
      const fake = fakeBucket(JSON.stringify({version: 1, entries: [entry('old')]} as QueryHistory));

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['new', 'old']);
      // Persisted via PutObject (overwrite).
      expect(JSON.parse(fake.stored() as string).entries[0].queryExecutionId).toBe('new');
    });

    it('caps the list at QUERY_HISTORY_MAX, dropping the oldest', async () => {
      const existing = Array.from({length: 100}, (_, i) => entry(`old-${i}`));
      fakeBucket(JSON.stringify({version: 1, entries: existing} as QueryHistory));

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries).toHaveLength(100);
      expect(result.data.entries[0].queryExecutionId).toBe('new');
      // old-99 (the previous oldest) is dropped.
      expect(result.data.entries.at(-1)?.queryExecutionId).toBe('old-98');
    });

    it('starts a fresh history when the file is absent', async () => {
      fakeBucket(null);

      const result = await appendQueryHistory('alice', entry('first'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['first']);
    });
  });

  describe('updateQueryHistoryEntry', () => {
    it('updates a matching entry in place and writes back', async () => {
      fakeBucket(JSON.stringify({version: 1, entries: [entry('q1')]} as QueryHistory));

      const result = await updateQueryHistoryEntry('alice', 'q1', {
        status: 'SUCCEEDED',
        dataScannedBytes: 2048,
        durationMs: 120
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries[0]).toMatchObject({
        queryExecutionId: 'q1',
        status: 'SUCCEEDED',
        dataScannedBytes: 2048,
        durationMs: 120
      });
    });

    it('is a no-op success (no write) for an unknown id', async () => {
      const fake = fakeBucket(JSON.stringify({version: 1, entries: [entry('q1')]} as QueryHistory));

      const result = await updateQueryHistoryEntry('alice', 'unknown', {
        status: 'FAILED'
      });

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.entries[0].status).toBeUndefined();
      // Only the read happened — no PutObject.
      expect(fake.send).toHaveBeenCalledTimes(1);
    });
  });
});

// ─── from savedQueries.service.test.ts ───

describe('savedQueries.service', () => {
  const mockGetClient = getS3Client as unknown as MockedFunction<() => Promise<unknown>>;

  // Stateful fake user-space bucket: GetObject reads the stored JSON (throws
  // NoSuchKey when absent); a command carrying a Body is a PutObject overwrite.
  // A DeleteObjectCommand would carry no Body and no read intent — tracked so we
  // can assert it's NEVER issued (delete is IAM-denied in athenaresults/).
  function fakeBucket(initial: string | null) {
    let stored = initial;
    const commands: string[] = [];
    const send = vi.fn(async (cmd: {constructor: {name: string}; input: {Body?: string}}) => {
      commands.push(cmd.constructor.name);
      if (cmd.input.Body !== undefined) {
        stored = cmd.input.Body;
        return {};
      }
      if (stored === null) {
        throw Object.assign(new Error('missing'), {name: 'NoSuchKey'});
      }
      const body = stored;
      return {Body: {transformToString: async () => body}};
    });
    mockGetClient.mockResolvedValue({success: true, data: {send}});
    return {send, stored: () => stored, commands};
  }

  function sq(id: string, name = id, sql = 'SELECT 1'): SavedQuery {
    return {
      id,
      name,
      sql,
      database: 'alice',
      createdAt: '2026-06-18T10:00:00.000Z',
      updatedAt: '2026-06-18T10:00:00.000Z'
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('getSavedQueries', () => {
    it('returns an empty store (no error) when the file is absent', async () => {
      fakeBucket(null);
      const result = await getSavedQueries('alice');
      expect(result).toEqual({success: true, data: {version: 1, queries: []}});
    });

    it('reads and parses an existing store', async () => {
      fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));
      const result = await getSavedQueries('alice');
      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.queries.map((q) => q.id)).toEqual(['a']);
    });

    it('falls back to empty on a malformed file', async () => {
      fakeBucket('not json{');
      const result = await getSavedQueries('alice');
      expect(result).toEqual({success: true, data: {version: 1, queries: []}});
    });
  });

  describe('upsertSavedQuery', () => {
    it('creates a new query (prepended) when the id is unseen', async () => {
      const fake = fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));
      const result = await upsertSavedQuery('alice', sq('b'));
      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.queries.map((q) => q.id)).toEqual(['b', 'a']);
      expect((JSON.parse(fake.stored() as string) as SavedQueriesStore).queries).toHaveLength(2);
    });

    it('replaces in place when the id already exists', async () => {
      fakeBucket(
        JSON.stringify({
          version: 1,
          queries: [sq('a', 'A', 'SELECT 1'), sq('b')]
        } as SavedQueriesStore)
      );
      const result = await upsertSavedQuery('alice', sq('a', 'A2', 'SELECT 2'));
      expect(result.success).toBe(true);
      if (!result.success) return;
      // Same position, updated content.
      expect(result.data.queries.map((q) => q.id)).toEqual(['a', 'b']);
      expect(result.data.queries[0].name).toBe('A2');
      expect(result.data.queries[0].sql).toBe('SELECT 2');
    });
  });

  describe('removeSavedQuery', () => {
    it('rewrites the JSON without the entry — never an S3 delete', async () => {
      const fake = fakeBucket(
        JSON.stringify({
          version: 1,
          queries: [sq('a'), sq('b')]
        } as SavedQueriesStore)
      );
      const result = await removeSavedQuery('alice', 'a');
      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.queries.map((q) => q.id)).toEqual(['b']);
      // Persisted via overwrite; no DeleteObjectCommand ever issued.
      expect(fake.commands).not.toContain('DeleteObjectCommand');
      expect(fake.commands).toContain('PutObjectCommand');
    });

    it('is a no-op success for an unknown id (no write)', async () => {
      const fake = fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));
      const result = await removeSavedQuery('alice', 'missing');
      expect(result.success).toBe(true);
      expect(fake.commands).not.toContain('PutObjectCommand');
    });
  });
});
