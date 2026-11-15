import {beforeEach, describe, expect, it, vi} from 'vitest';
import {mockApi, apiFailure} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {
  getQueryResults,
  getQueryRowCount,
  getQueryStatus,
  getTableDdl,
  runQuery,
  runStatementToCompletion,
  stopQuery
} from './athena.service';
import {getDatabase, listTables} from './glue.service';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

/**
 * The catalog services, now over the API.
 *
 * Every assertion that used to drive the AWS SDK is either here, or moved to the Python suite
 * with its reasoning carried over, or kept on both sides. The disposition table in the delivery
 * doc is the record; what this file holds is the browser's half — the wire → domain mapping, the
 * loops that stayed here, and the codes a surface maps to wording.
 *
 * **The Athena-shaped arithmetic is deliberately absent.** The `+1` overfetch, the 1000 clamp and
 * the repeated-header-row drop are asserted in `lambdas/api/test_athena_routes.py` now. Asserting
 * them here too would be testing a fake rather than the thing that does the work.
 */
describe('the catalog services over the API', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  describe('runQuery', () => {
    it('sends the statement and nothing that names the caller or where results go', async () => {
      // MOVED to Python, and strengthened there: the workgroup, the output location and the
      // username are derived from the verified claim and this function's own environment. What
      // is asserted here is the half this side owns — that none of the three is on the wire.
      // `username` stays on the signature so no call site changed.
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});

      await runQuery({sql: 'SELECT 1', username: 'alice'});

      expect(api.bodyFor('athena.start')).toEqual({sql: 'SELECT 1'});
      expect(JSON.stringify(api.bodyFor('athena.start'))).not.toContain('alice');
    });

    it('sends the database only when the caller named one', async () => {
      // Queries carry no active database, so every base table is fully qualified. A present but
      // empty context changes what resolves, which is why the key must be absent rather than
      // blank — the API omits `QueryExecutionContext` entirely on this shape.
      api.onEach('athena.start', [
        {success: true, data: {queryExecutionId: 'q-1'}},
        {success: true, data: {queryExecutionId: 'q-2'}}
      ]);

      await runQuery({sql: 'SELECT 1', username: 'alice'});
      await runQuery({sql: 'SHOW CREATE TABLE a.b', username: 'alice', database: 'a'});

      expect(api.calls[0].body).toEqual({sql: 'SELECT 1'});
      expect(api.calls[1].body).toEqual({sql: 'SHOW CREATE TABLE a.b', database: 'a'});
    });

    it('returns the failure envelope rather than throwing', async () => {
      // KEPT, and widened: what used to be a client-minted `AthenaNoExecutionId` is now a 500
      // from the API, and every service here still returns rather than throws.
      api.on('athena.start', apiFailure('InternalError'));

      const result = await runQuery({sql: 'SELECT 1', username: 'alice'});

      expect(result).toEqual({success: false, error: {message: '', code: 'InternalError'}});
    });
  });

  describe('runStatementToCompletion', () => {
    it('gives up with `Timeout` at the poll ceiling, and stops polling', async () => {
      // The ceiling is a constant the service keeps to itself (90 polls, 400 ms apart);
      // the number here is that constant, and a change to it is a change to this test.
      vi.useFakeTimers();
      try {
        api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
        api.on('athena.status', {
          success: true,
          data: {
            queryExecutionId: 'q-1',
            state: 'RUNNING',
            stateChangeReason: null,
            dataScannedBytes: null,
            engineExecutionTimeMillis: null,
            outputLocation: null
          }
        });

        const pending = runStatementToCompletion({sql: 'SELECT 1', database: 'alice', username: 'alice'});
        await vi.advanceTimersByTimeAsync(400 * 90);
        const result = await pending;

        expect(result).toEqual({success: false, error: expect.objectContaining({code: 'Timeout'})});
        expect(api.routes().filter((route) => route === 'athena.status')).toHaveLength(90);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe('getQueryStatus', () => {
    it('maps the wire onto QueryStatus, turning null into absent', async () => {
      // BOTH sides: Python maps the botocore shape, this maps the wire shape. The domain type
      // says a field is absent and the wire says `null`, and nothing downstream was changed to
      // learn the difference.
      api.on('athena.status', {
        success: true,
        data: {
          queryExecutionId: 'q-1',
          state: 'SUCCEEDED',
          stateChangeReason: null,
          dataScannedBytes: 1024,
          engineExecutionTimeMillis: 20,
          outputLocation: 's3://bucket/alice/athenaresults/q-1.csv'
        }
      });

      const result = await getQueryStatus('q-1');

      expect(result).toEqual({
        success: true,
        data: {
          queryExecutionId: 'q-1',
          state: 'SUCCEEDED',
          stateChangeReason: undefined,
          dataScannedBytes: 1024,
          engineExecutionTimeMillis: 20,
          outputLocation: 's3://bucket/alice/athenaresults/q-1.csv'
        }
      });
      expect(api.paramsFor('athena.status')).toEqual({queryExecutionId: 'q-1'});
    });

    it('carries a failed execution through as a SUCCESS, with its reason intact', async () => {
      // The load-bearing one. A FAILED execution is data about the query, not a failed request:
      // six authored sentences are chosen by reading this reason, and a service that mapped this
      // onto the error arm would retire all six while looking perfectly correct.
      api.on('athena.status', {
        success: true,
        data: {
          queryExecutionId: 'q-1',
          state: 'FAILED',
          stateChangeReason: 'SYNTAX_ERROR: line 1:8: Column x cannot be resolved',
          dataScannedBytes: null,
          engineExecutionTimeMillis: null,
          outputLocation: null
        }
      });

      const result = await getQueryStatus('q-1');

      expect(result.success).toBe(true);
      expect(result.success && result.data.state).toBe('FAILED');
      expect(result.success && result.data.stateChangeReason).toBe(
        'SYNTAX_ERROR: line 1:8: Column x cannot be resolved'
      );
    });
  });

  describe('stopQuery', () => {
    it('names the execution and returns nothing', async () => {
      api.on('athena.stop', {success: true, data: {}});

      const result = await stopQuery('q-7');

      expect(api.paramsFor('athena.stop')).toEqual({queryExecutionId: 'q-7'});
      expect(result).toEqual({success: true, data: undefined});
    });

    it('maps a failure to a ServiceResult error (never throws)', async () => {
      api.on('athena.stop', apiFailure('AccessDenied'));

      await expect(stopQuery('q-7')).resolves.toEqual({
        success: false,
        error: {message: '', code: 'AccessDenied'}
      });
    });
  });

  describe('getQueryResults', () => {
    it('normalizes column types and preserves a NULL cell as distinct from an empty one', async () => {
      // BOTH sides. Python asserts the distinction on the raw response body, because that is
      // where a `?? ''` would destroy it; this asserts the parsed page still carries it, because
      // that is what the Value panel reads. `normalizeColumnType` stays client-side, so the wire
      // carries Athena's own type string and this turns it into the name the schema rail shows.
      api.on('athena.results', {
        success: true,
        data: {
          columns: [
            {name: 'id', type: 'integer'},
            {name: 'name', type: 'varchar'}
          ],
          rows: [
            ['1', null],
            ['2', '']
          ],
          nextToken: 'tok2'
        }
      });

      const result = await getQueryResults({queryExecutionId: 'q-1'});

      expect(result).toEqual({
        success: true,
        data: {
          columns: [
            {name: 'id', type: 'int'},
            {name: 'name', type: 'string'}
          ],
          rows: [
            ['1', null],
            ['2', '']
          ],
          nextToken: 'tok2'
        }
      });
    });

    it('asks for its own page size rather than depending on the server default', async () => {
      // The two agree today. A caller that stopped naming its page size would be depending on
      // them continuing to, across two repositories and two deploys.
      api.onEach('athena.results', [
        {success: true, data: {columns: [], rows: [], nextToken: null}},
        {success: true, data: {columns: [], rows: [], nextToken: null}}
      ]);

      await getQueryResults({queryExecutionId: 'q-1'});
      await getQueryResults({queryExecutionId: 'q-1', maxRows: 999, nextToken: 'tok'});

      expect(api.calls[0].query).toEqual({maxRows: '100'});
      expect(api.calls[1].query).toEqual({maxRows: '999', nextToken: 'tok'});
    });

    it('returns an empty page (no error) for a DDL query with no result set', async () => {
      api.on('athena.results', {success: true, data: {columns: [], rows: [], nextToken: null}});

      await expect(getQueryResults({queryExecutionId: 'q-1'})).resolves.toEqual({
        success: true,
        data: {columns: [], rows: [], nextToken: undefined}
      });
    });

    it('surfaces a too-early read as its own code, not the generic failure', async () => {
      // The condition that reached users as "Contact the Administrator" on an ordinary first
      // load. The API now resolves it to a code, which `errorMessages` maps to "still running".
      api.on('athena.results', apiFailure('QueryNotFinished'));

      const result = await getQueryResults({queryExecutionId: 'q-1'});

      expect(result).toEqual({success: false, error: {message: '', code: 'QueryNotFinished'}});
    });
  });

  describe('getQueryRowCount', () => {
    it('names the execution and passes Athena’s count through, zero included', async () => {
      api.onEach('athena.rowCount', [
        {success: true, data: {rowCount: 10_000_000, pending: false}},
        {success: true, data: {rowCount: 0, pending: false}},
        {success: true, data: {rowCount: null, pending: true}}
      ]);

      const counted = await getQueryRowCount('q-1');
      const empty = await getQueryRowCount('q-1');
      const pending = await getQueryRowCount('q-1');

      expect(api.paramsFor('athena.rowCount')).toEqual({queryExecutionId: 'q-1'});
      expect(counted).toEqual({success: true, data: {rowCount: 10_000_000, pending: false}});
      expect(empty).toEqual({success: true, data: {rowCount: 0, pending: false}});
      expect(pending).toEqual({success: true, data: {rowCount: null, pending: true}});
    });

    it('maps a refusal to a ServiceResult error (never throws)', async () => {
      api.on('athena.rowCount', apiFailure('NotFound'));

      await expect(getQueryRowCount('q-1')).resolves.toEqual({
        success: false,
        error: {message: '', code: 'NotFound'}
      });
    });
  });

  describe('runStatementToCompletion', () => {
    it('runs and polls to a terminal state, returning the final status', async () => {
      // KEPT — the loop never left the browser. It polls over API calls now, and nothing else
      // about it moved.
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.onEach('athena.status', [
        {success: true, data: statusBody('RUNNING')},
        {success: true, data: statusBody('SUCCEEDED')}
      ]);

      const result = await runStatementToCompletion({
        sql: 'SHOW CREATE TABLE db.t',
        database: 'db',
        username: 'alice'
      });

      expect(result.success && result.data.state).toBe('SUCCEEDED');
      expect(api.countOf('athena.status')).toBe(2);
    });

    it('stops polling when the caller has navigated away', async () => {
      // The abort still stops this browser waiting. It does NOT stop the statement, and it never
      // did — what changed is only that the request in flight is now an API call.
      const controller = new AbortController();
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.on('athena.status', {success: true, data: statusBody('RUNNING')});
      controller.abort();

      const result = await runStatementToCompletion({
        sql: 'SHOW CREATE TABLE db.t',
        database: 'db',
        username: 'alice',
        signal: controller.signal
      });

      expect(result).toEqual({
        success: false,
        error: {message: 'Stopped waiting for the query.', code: 'Abandoned'}
      });
      expect(api.countOf('athena.status')).toBe(0);
    });
  });

  describe('getTableDdl', () => {
    it('runs SHOW CREATE TABLE and joins the result rows into the DDL', async () => {
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.on('athena.status', {success: true, data: statusBody('SUCCEEDED')});
      api.on('athena.results', {
        success: true,
        data: {
          columns: [{name: 'createtab_stmt', type: 'varchar'}],
          rows: [['CREATE EXTERNAL TABLE db.t ('], ['  id int'], [')']],
          nextToken: null
        }
      });

      const result = await getTableDdl({database: 'db', table: 't', username: 'alice'});

      expect(result).toEqual({
        success: true,
        data: 'CREATE EXTERNAL TABLE db.t (\n  id int\n)'
      });
      expect(api.bodyFor('athena.start')).toEqual({
        sql: 'SHOW CREATE TABLE `db`.`t`',
        database: 'db'
      });
      expect(api.queryFor('athena.results')).toEqual({maxRows: '999'});
    });

    // Off the query list, so a list-driven quote would have sent it bare, which Hive refuses.
    it('backticks a table named with a word only Hive reserves, which bare is a parse error', async () => {
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.on('athena.status', {success: true, data: statusBody('SUCCEEDED')});
      api.on('athena.results', {
        success: true,
        data: {columns: [{name: 'createtab_stmt', type: 'varchar'}], rows: [['CREATE TABLE']], nextToken: null}
      });

      await getTableDdl({database: 'alice', table: 'exchange', username: 'alice'});

      expect(api.bodyFor('athena.start')).toEqual({sql: 'SHOW CREATE TABLE `alice`.`exchange`', database: 'alice'});
    });

    it('runs SHOW CREATE VIEW for a view', async () => {
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.on('athena.status', {success: true, data: statusBody('SUCCEEDED')});
      api.on('athena.results', {
        success: true,
        data: {columns: [{name: 'createtab_stmt', type: 'varchar'}], rows: [['CREATE VIEW v AS']], nextToken: null}
      });

      await getTableDdl({database: 'db', table: 'v', username: 'alice', isView: true});

      expect(api.bodyFor('athena.start')).toEqual({sql: 'SHOW CREATE VIEW db.v', database: 'db'});
    });

    it('double-quotes a view name that bare is a parse error, SHOW CREATE VIEW being Trino', async () => {
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.on('athena.status', {success: true, data: statusBody('SUCCEEDED')});
      api.on('athena.results', {
        success: true,
        data: {columns: [{name: 'create view', type: 'varchar'}], rows: [['CREATE VIEW']], nextToken: null}
      });

      await getTableDdl({database: 'team space', table: 'values', username: 'alice', isView: true});

      expect(api.bodyFor('athena.start')).toEqual({
        sql: 'SHOW CREATE VIEW "team space"."values"',
        database: 'team space'
      });
    });

    it('returns an error when the statement does not succeed', async () => {
      api.on('athena.start', {success: true, data: {queryExecutionId: 'q-1'}});
      api.on('athena.status', {
        success: true,
        data: {...statusBody('FAILED'), stateChangeReason: 'Table not found'}
      });

      const result = await getTableDdl({database: 'db', table: 'missing', username: 'alice'});

      expect(result).toEqual({
        success: false,
        error: {message: 'Table not found', code: 'FAILED'}
      });
    });
  });

  describe('getDatabase', () => {
    it('returns the name', async () => {
      api.on('catalog.database.get', {success: true, data: {name: 'alice'}});

      const result = await getDatabase('alice');

      expect(result).toEqual({success: true, data: {name: 'alice'}});
      expect(api.paramsFor('catalog.database.get')).toEqual({database: 'alice'});
    });

    it('surfaces a missing database as NotFound', async () => {
      // MOVED to Python (the 404) and KEPT here (the code a surface reads). The sentence the old
      // service authored — 'Database "x" does not exist yet.' — was already discarded by
      // `toUserMessage`'s non-passthrough `NotFound` rule, so nothing user-visible moved.
      api.on('catalog.database.get', apiFailure('NotFound'));

      const result = await getDatabase('nope');

      expect(result).toEqual({success: false, error: {message: '', code: 'NotFound'}});
    });
  });

  describe('listTables', () => {
    it('walks every page and maps null onto absent', async () => {
      // KEPT on the client, now over the API's `nextToken`. The API answers one page per
      // request, so this loop is what makes `listTables` still return every table — and
      // `useSchema` never learned that anything changed.
      api.onEach('catalog.tables.list', [
        {
          success: true,
          data: {
            items: [
              {
                name: 'sales',
                columns: [{name: 'id', type: 'bigint'}],
                tableType: 'EXTERNAL_TABLE',
                location: 's3://bucket/alice/sales/'
              }
            ],
            nextToken: 'page2'
          }
        },
        {
          success: true,
          data: {
            items: [{name: 'bare', columns: [], tableType: null, location: null}],
            nextToken: null
          }
        }
      ]);

      const result = await listTables('alice');

      expect(result).toEqual({
        success: true,
        data: [
          {
            name: 'sales',
            columns: [{name: 'id', type: 'bigint'}],
            tableType: 'EXTERNAL_TABLE',
            location: 's3://bucket/alice/sales/'
          },
          {name: 'bare', columns: [], tableType: undefined, location: undefined}
        ]
      });
      expect(api.countOf('catalog.tables.list')).toBe(2);
      expect(api.calls[0].query).toEqual({});
      expect(api.calls[1].query).toEqual({nextToken: 'page2'});
    });

    it('stops the walk on a failure rather than returning a partial list', async () => {
      // A partial list reads as "this database has three tables" to every consumer. The old
      // service could not produce one — an SDK failure threw out of the loop — and neither can
      // this one, but only because it returns rather than breaks.
      api.onEach('catalog.tables.list', [
        {success: true, data: {items: [{name: 'a', columns: [], tableType: null, location: null}], nextToken: 'p2'}},
        apiFailure('AccessDenied')
      ]);

      const result = await listTables('alice');

      expect(result).toEqual({success: false, error: {message: '', code: 'AccessDenied'}});
    });

    it('treats a not-yet-created database as an empty schema, not an error', async () => {
      // MOVED to Python: the API answers 200 with an empty page for `EntityNotFoundException`,
      // because the workspace lists a space's tables before anything has created any.
      api.on('catalog.tables.list', {success: true, data: {items: [], nextToken: null}});

      await expect(listTables('brand-new')).resolves.toEqual({success: true, data: []});
    });
  });
});

/** A status body with everything absent but the state, which is what most of these need. */
function statusBody(state: string) {
  return {
    queryExecutionId: 'q-1',
    state,
    stateChangeReason: null,
    dataScannedBytes: null,
    engineExecutionTimeMillis: null,
    outputLocation: null
  };
}
