import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiFailure, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {enqueueTableBuild, enqueueTableRefresh, suggestTableName, isValidTableName} from './tableBuild.service';
import type {TableBuildRequest} from './tableBuild.types';
import type {TableRefreshRequest} from './tableRefresh.types';

vi.mock('../../lib/apiClient', () => ({apiRequest: vi.fn()}));

/**
 * The create and refresh enqueues, now over the API.
 *
 * **The FIFO keys are deliberately absent from this file.** The group id was the database name —
 * so two builds against one catalog database serialize — and the dedup id was the minted request
 * id; both are computed server-side now and replayed against vectors captured from this service in
 * `lambdas/api/test_fifo_derivations.py`, for a personal and a shared space alike. So is the
 * `idToken` field, and so is `mode: 'refresh'`, which the API now STAMPS: that a refresh and only
 * a refresh carries it is asserted in `lambdas/api/test_enqueue_routes.py`, against the route's
 * own declaration rather than against a copy of the string.
 *
 * What stays here is the browser's half — the request id it mints, the fields it forwards, the
 * empty key list a refresh is required to send, and the projection bounds it stringifies.
 */
const flatReq: TableBuildRequest = {
  space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/sales/2026/', database: 'alice'},
  tableName: 'sales_2026',
  partitionKeys: []
};

const partitionedReq: TableBuildRequest = {
  space: {kind: 'shared', bucket: 'dat-prod-shared-space', prefix: 'salesdata/events/', database: 'salesdata'},
  tableName: 'events',
  partitionKeys: [
    {name: 'year', type: 'integer', range: [2020, 2026], digits: 4},
    {name: 'day', type: 'date', range: ['2020-01-01', '2026-01-01'], format: 'yyyy-MM-dd'},
    {name: 'region', type: 'string', values: ['us', 'eu']}
  ]
};

describe('enqueueTableBuild', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the create once, minting the request id, with the caller’s space and table name', async () => {
    api.on('tableBuild.create', {success: true, data: {requestId: 'echoed'}});

    const result = await enqueueTableBuild(flatReq);

    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['tableBuild.create']);
    // `toEqual`, not `toMatchObject`: that no `mode` and no claimed identity ride along is the
    // assertion. `mode` is the API's to stamp, and a body claiming one is refused at the door.
    expect(api.bodyFor('tableBuild.create')).toEqual({
      requestId: expect.any(String),
      space: flatReq.space,
      tableName: 'sales_2026',
      partitionKeys: []
    });
  });

  it('stringifies a projection bound on the way to the wire, per key variant', async () => {
    // The contract's type vocabulary has no union of object shapes, so the three key variants are
    // flattened into one shape whose bounds are strings. That is only safe because the DDL builder
    // interpolates the pair into one property and does no arithmetic — which is asserted against
    // the builder itself in `lambdas/api/test_enqueue_routes.py`, not argued here. This is the
    // browser half: the mapping happens, and it happens for the integer key too.
    api.on('tableBuild.create', {success: true, data: {requestId: 'echoed'}});

    await enqueueTableBuild(partitionedReq);

    expect((api.bodyFor('tableBuild.create') as {partitionKeys: unknown}).partitionKeys).toEqual([
      {name: 'year', type: 'integer', range: ['2020', '2026'], digits: 4},
      {name: 'day', type: 'date', range: ['2020-01-01', '2026-01-01'], format: 'yyyy-MM-dd'},
      {name: 'region', type: 'string', values: ['us', 'eu']}
    ]);
  });

  it('defaults partitionKeys to [] when the caller omits them', async () => {
    // The wire field is required, so an omitted list has to become an empty one here or the
    // request is refused as malformed rather than read as flat.
    api.on('tableBuild.create', {success: true, data: {requestId: 'echoed'}});

    await enqueueTableBuild({...flatReq, partitionKeys: undefined as unknown as []});

    expect((api.bodyFor('tableBuild.create') as {partitionKeys: unknown}).partitionKeys).toEqual([]);
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('tableBuild.create', apiFailure('RateLimited'));

    const result = await enqueueTableBuild(flatReq);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('RateLimited');
  });
});

const refreshReq: TableRefreshRequest = {
  space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/sales/2026/', database: 'alice'},
  tableName: 'sales_2026'
};

describe('enqueueTableRefresh', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest));
  });

  it('sends the refresh once, field by field, with the empty key list a refresh must carry', async () => {
    api.on('tableBuild.refresh', {success: true, data: {requestId: 'echoed'}});

    const result = await enqueueTableRefresh(refreshReq);

    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['tableBuild.refresh']);
    expect(api.bodyFor('tableBuild.refresh')).toEqual({
      requestId: expect.any(String),
      space: refreshReq.space,
      tableName: 'sales_2026',
      // A refresh reconstructs the table's existing keys — it never redeclares them.
      partitionKeys: []
    });
  });

  it('omits allowRemovals unless the opt-in was ticked, and sends it when it was', async () => {
    // The plane validates the flag rather than coercing it: absent is a different request from
    // false, so sending `allowRemovals: false` would be a removal opt-in the user never gave.
    api.on('tableBuild.refresh', {success: true, data: {requestId: 'echoed'}});

    await enqueueTableRefresh({...refreshReq, allowRemovals: false});
    await enqueueTableRefresh({...refreshReq, allowRemovals: true});

    expect(api.calls[0].body).not.toHaveProperty('allowRemovals');
    expect(api.calls[1].body).toMatchObject({allowRemovals: true});
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('tableBuild.refresh', apiFailure('RateLimited'));

    const result = await enqueueTableRefresh(refreshReq);

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('RateLimited');
  });
});

describe('suggestTableName', () => {
  it('lowercases and replaces non-conforming chars with underscore', () => {
    expect(suggestTableName('Sales 2026')).toBe('sales_2026');
    expect(suggestTableName('my-data.set')).toBe('my_data_set');
  });

  it('ensures a leading letter', () => {
    expect(suggestTableName('2026')).toBe('t_2026');
    expect(suggestTableName('_hidden')).toBe('hidden');
  });

  it('trims to the max length without a trailing underscore', () => {
    const long = 'a'.repeat(80);
    const s = suggestTableName(long);
    expect(s.length).toBe(63);
    expect(s.endsWith('_')).toBe(false);
  });

  it('produces a valid name for a typical folder', () => {
    expect(isValidTableName(suggestTableName('Sales 2026'))).toBe(true);
  });
});
