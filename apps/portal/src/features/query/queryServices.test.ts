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
  // NoSuchKey when absent); PutObject (input has a Body) overwrites it; CopyObject
  // (input has a CopySource) is RECORDED rather than stored, so `stored()` keeps
  // answering for the document under test while `copies` shows what was set aside.
  // `copyFails` denies the copy, which is the only way to reach the refusal that must
  // never become a silent overwrite.
  function fakeBucket(initial: string | null, opts: {copyFails?: boolean} = {}) {
    let stored = initial;
    const commands: string[] = [];
    const copies: {key: string; source: string}[] = [];
    const send = vi.fn(
      async (cmd: {constructor: {name: string}; input: {Body?: string; Key?: string; CopySource?: string}}) => {
        commands.push(cmd.constructor.name);
        if (cmd.input.CopySource !== undefined) {
          if (opts.copyFails) throw Object.assign(new Error('denied'), {name: 'AccessDenied'});
          copies.push({key: cmd.input.Key as string, source: cmd.input.CopySource});
          return {};
        }
        if (cmd.input.Body !== undefined) {
          stored = cmd.input.Body;
          return {};
        }
        if (stored === null) {
          throw Object.assign(new Error('missing'), {name: 'NoSuchKey'});
        }
        const body = stored;
        return {Body: {transformToString: async () => body}};
      }
    );
    mockGetClient.mockResolvedValue({success: true, data: {send}});
    return {send, stored: () => stored, commands, copies};
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

  // ── The write path refuses a body it cannot read ─────────────────────────────
  // Same hazard as savedQueries, and worse to lose: this file is the only record
  // of a query beyond Athena's ~45-day retention, and the user cannot re-create it
  // (there is no clear/delete, by design).
  //
  // As there, only `append` could actually commit the empty document; `update` took
  // its not-found no-op branch first. `update` is covered because that no-op was
  // reported as success carrying the EMPTY history, which `useQueryHistory`'s
  // onWriteSuccess seeded into the cache — blanking the panel on a read fault.
  describe('the read-modify-write path never overwrites a history it cannot read', () => {
    const newer = [JSON.stringify({version: 2, entries: [entry('q1')]}), JSON.stringify({version: 2})];

    it('append sets the unreadable body aside, then writes', async () => {
      const fake = fakeBucket('not json{');

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(true);
      expect(result.data.entries.map((e) => e.queryExecutionId)).toEqual(['new']);
      expect(fake.commands).toEqual(['GetObjectCommand', 'CopyObjectCommand', 'PutObjectCommand']);
      expect(fake.copies[0].key).toMatch(/^alice\/user_settings\/query-history\.json\.unreadable-\d{8}T\d{6}Z\.json$/);
      expect(fake.copies[0].source).toBe('user-bucket/alice/user_settings/query-history.json');
    });

    it('update forfeits its unknown-id shortcut after a recovery, so the document is repaired', async () => {
      const fake = fakeBucket('not json{');

      const result = await updateQueryHistoryEntry('alice', 'q1', {status: 'SUCCEEDED'});

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(true);
      expect(JSON.parse(fake.stored() as string)).toEqual({version: 1, entries: []});
    });

    it('refuses and writes nothing when the copy fails', async () => {
      const fake = fakeBucket('not json{', {copyFails: true});

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('QueryHistoryQuarantineFailed');
      expect(fake.commands).not.toContain('PutObjectCommand');
      expect(fake.stored()).toBe('not json{');
    });

    it.each(newer)('refuses a NEWER document without copying or writing it (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await appendQueryHistory('alice', entry('new'));

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('QueryHistoryNewerVersion');
      expect(fake.commands).toEqual(['GetObjectCommand']);
      expect(fake.stored()).toBe(body);
    });

    it.each(newer)('refuses a NEWER document on the update path too (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await updateQueryHistoryEntry('alice', 'q1', {status: 'SUCCEEDED'});

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('QueryHistoryNewerVersion');
      expect(fake.commands).toEqual(['GetObjectCommand']);
      expect(fake.stored()).toBe(body);
    });

    it('leaves the DISPLAY read forgiving, for a newer document as well as a corrupt one', async () => {
      fakeBucket('not json{');
      expect(await getQueryHistory('alice')).toEqual({success: true, data: {version: 1, entries: []}});

      fakeBucket(JSON.stringify({version: 2, entries: [entry('q1')]}));
      expect(await getQueryHistory('alice')).toEqual({success: true, data: {version: 1, entries: []}});
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
  // As in `queryHistory.service` above: Get reads, Put overwrites, Copy is recorded.
  function fakeBucket(initial: string | null, opts: {copyFails?: boolean} = {}) {
    let stored = initial;
    const commands: string[] = [];
    const copies: {key: string; source: string}[] = [];
    const send = vi.fn(
      async (cmd: {constructor: {name: string}; input: {Body?: string; Key?: string; CopySource?: string}}) => {
        commands.push(cmd.constructor.name);
        if (cmd.input.CopySource !== undefined) {
          if (opts.copyFails) throw Object.assign(new Error('denied'), {name: 'AccessDenied'});
          copies.push({key: cmd.input.Key as string, source: cmd.input.CopySource});
          return {};
        }
        if (cmd.input.Body !== undefined) {
          stored = cmd.input.Body;
          return {};
        }
        if (stored === null) {
          throw Object.assign(new Error('missing'), {name: 'NoSuchKey'});
        }
        const body = stored;
        return {Body: {transformToString: async () => body}};
      }
    );
    mockGetClient.mockResolvedValue({success: true, data: {send}});
    return {send, stored: () => stored, commands, copies};
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

  // ── The write path refuses a body it cannot read ─────────────────────────────
  // The display read is forgiving on purpose (a corrupt file must not lock the
  // user out of the page), but the write is an unconditional PutObject, so the
  // same forgiveness on the write path COMMITTED the empty fallback.
  //
  // Only `upsert` was destructive: it wrote `{queries: [theNewOne]}` over the whole
  // library. `remove` was NOT — the forgiving read gave it an empty store, the
  // filter left the length unchanged, and it took the unknown-id no-op branch
  // before any write. It is covered here because it reported that no-op as SUCCESS
  // against a store it had failed to read, which `useSavedQueries.onWriteSuccess`
  // then seeded into the cache — blanking the panel without touching S3.
  describe('the read-modify-write path never overwrites a store it cannot read', () => {
    const unparseable = ['not json{', JSON.stringify(['queries']), JSON.stringify({queries: []})];

    // A future schema bump read by a tab still running today's code produces a
    // perfectly valid document this build cannot read — the trigger that needs no
    // corruption at all, and the one outcome that must be left strictly alone. The
    // second body has no `queries` at all: newer is newer WHATEVER else it contains,
    // because a newer schema is free to have renamed the field we validate.
    const newer = [JSON.stringify({version: 2, queries: [sq('a')]}), JSON.stringify({version: 2})];

    it.each(unparseable)('upsert sets the unreadable body aside, then writes (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await upsertSavedQuery('alice', sq('new'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(true);
      // The recovered store holds ONLY the query being saved — the point of telling
      // the user, and of keeping the copy.
      expect(result.data.queries.map((q) => q.id)).toEqual(['new']);
      // The copy is a precondition, not a courtesy: it lands BEFORE the overwrite.
      expect(fake.commands).toEqual(['GetObjectCommand', 'CopyObjectCommand', 'PutObjectCommand']);
      expect(fake.copies).toHaveLength(1);
      expect(fake.copies[0].key).toMatch(/^alice\/user_settings\/saved-queries\.json\.unreadable-\d{8}T\d{6}Z\.json$/);
      expect(fake.copies[0].source).toBe('user-bucket/alice/user_settings/saved-queries.json');
    });

    it('remove forfeits its unknown-id shortcut after a recovery, so the document is repaired', async () => {
      // Without this the store would be quarantined and then left exactly as broken
      // as it was found: the filter changes nothing against an empty store, and the
      // no-op branch returns before any write.
      const fake = fakeBucket('not json{');

      const result = await removeSavedQuery('alice', 'gone');

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(true);
      expect(fake.commands).toContain('PutObjectCommand');
      expect(JSON.parse(fake.stored() as string)).toEqual({version: 1, queries: []});
    });

    it('refuses and writes nothing when the copy fails', async () => {
      const fake = fakeBucket('not json{', {copyFails: true});

      const result = await upsertSavedQuery('alice', sq('new'));

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('SavedQueriesQuarantineFailed');
      // The point of the test: a failed quarantine never becomes a silent overwrite.
      expect(fake.commands).not.toContain('PutObjectCommand');
      expect(fake.stored()).toBe('not json{');
    });

    it.each(newer)('refuses a NEWER document without copying or writing it (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await upsertSavedQuery('alice', sq('new'));

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('SavedQueriesNewerVersion');
      // Quarantining this would be the downgrade the whole spec exists to prevent.
      expect(fake.commands).toEqual(['GetObjectCommand']);
      expect(fake.stored()).toBe(body);
    });

    it.each(newer)('refuses a NEWER document on the remove path too (%#)', async (body) => {
      const fake = fakeBucket(body);

      const result = await removeSavedQuery('alice', 'a');

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe('SavedQueriesNewerVersion');
      expect(fake.commands).toEqual(['GetObjectCommand']);
      expect(fake.stored()).toBe(body);
    });

    it('reports an ordinary write as NOT recovered', async () => {
      fakeBucket(JSON.stringify({version: 1, queries: [sq('a')]} as SavedQueriesStore));

      const result = await upsertSavedQuery('alice', sq('b'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.recovered).toBe(false);
    });

    it('still creates the store when the object is genuinely ABSENT', async () => {
      // The refusal must not break the bootstrap case — absent has nothing to
      // lose, and treating it as a refusal would mean nobody could ever save a
      // first query.
      const fake = fakeBucket(null);

      const result = await upsertSavedQuery('alice', sq('first'));

      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.queries.map((q) => q.id)).toEqual(['first']);
      expect((JSON.parse(fake.stored() as string) as SavedQueriesStore).queries).toHaveLength(1);
    });

    it('leaves the DISPLAY read forgiving, and copies nothing while doing it', async () => {
      // The write path's business is scoped to the write path: the panel still
      // renders empty rather than erroring, which is the deliberate behaviour it
      // started with, and merely LOOKING at a broken document quarantines nothing.
      const fake = fakeBucket('not json{');
      expect(await getSavedQueries('alice')).toEqual({success: true, data: {version: 1, queries: []}});
      expect(fake.commands).toEqual(['GetObjectCommand']);

      fakeBucket(JSON.stringify({version: 2, queries: [sq('a')]}));
      expect(await getSavedQueries('alice')).toEqual({success: true, data: {version: 1, queries: []}});
    });
  });
});
