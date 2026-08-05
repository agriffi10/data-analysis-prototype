import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueTableBuild, enqueueTableRefresh, suggestTableName, isValidTableName} from './tableBuild.service';
import type {TableBuildRequest} from './tableBuild.types';
import type {TableRefreshRequest} from './tableRefresh.types';

const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-table-builder-requests.fifo';

type Cmd = {input: Record<string, unknown>};

function fakeQueue(rejectWith?: unknown) {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
  if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
  else send.mockResolvedValue({MessageId: 'm1'});
  mockGetSqs.mockResolvedValue({success: true, data: {send}});
  return {send};
}

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
    {name: 'region', type: 'string', values: ['us', 'eu']}
  ]
};

beforeEach(() => {
  vi.stubEnv('VITE_TABLE_BUILD_QUEUE_URL', QUEUE);
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('enqueueTableBuild', () => {
  it('builds the SPEC-067 envelope for a flat request and sends FIFO with group=database', async () => {
    const {send} = fakeQueue();
    const result = await enqueueTableBuild(flatReq);
    expect(result.success).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.QueueUrl).toBe(QUEUE);
    expect(cmd.input.MessageGroupId).toBe('alice'); // = space.database
    expect(cmd.input.MessageDeduplicationId).toEqual(expect.any(String));
    const body = JSON.parse(cmd.input.MessageBody as string);
    expect(body).toMatchObject({
      idToken: 'id-token-abc',
      space: flatReq.space,
      tableName: 'sales_2026',
      partitionKeys: []
    });
    // dedup id === requestId (correlation)
    expect(body.requestId).toBe(cmd.input.MessageDeduplicationId);
  });

  it('includes partitionKeys and groups by the shared database name', async () => {
    const {send} = fakeQueue();
    await enqueueTableBuild(partitionedReq);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.MessageGroupId).toBe('salesdata');
    const body = JSON.parse(cmd.input.MessageBody as string);
    expect(body.partitionKeys).toEqual(partitionedReq.partitionKeys);
    expect(body.space.kind).toBe('shared');
  });

  it('defaults partitionKeys to [] when omitted', async () => {
    const {send} = fakeQueue();
    await enqueueTableBuild({...flatReq, partitionKeys: undefined as unknown as []});
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body.partitionKeys).toEqual([]);
  });

  it('never puts a client-asserted actor in the body (only the ID token)', async () => {
    const {send} = fakeQueue();
    await enqueueTableBuild(flatReq);
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body).not.toHaveProperty('actor');
    expect(body).not.toHaveProperty('username');
  });

  it('fails when the queue URL is not configured', async () => {
    vi.stubEnv('VITE_TABLE_BUILD_QUEUE_URL', '');
    const {send} = fakeQueue();
    const result = await enqueueTableBuild(flatReq);
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('propagates an ID-token failure without sending', async () => {
    const {send} = fakeQueue();
    mockGetIdToken.mockResolvedValue({success: false, error: {message: 'no token'}});
    const result = await enqueueTableBuild(flatReq);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.message).toBe('no token');
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a typed error when SendMessage fails', async () => {
    fakeQueue({name: 'Throttling', message: 'slow down'});
    const result = await enqueueTableBuild(flatReq);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.code).toBe('Throttling');
  });
});

const refreshReq: TableRefreshRequest = {
  space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/sales/2026/', database: 'alice'},
  tableName: 'sales_2026'
};

describe('enqueueTableRefresh', () => {
  it('builds the SPEC-143 refresh envelope field by field', async () => {
    const {send} = fakeQueue();
    const result = await enqueueTableRefresh(refreshReq);
    expect(result.success).toBe(true);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.QueueUrl).toBe(QUEUE);
    expect(cmd.input.MessageGroupId).toBe('alice');
    const body = JSON.parse(cmd.input.MessageBody as string);
    expect(body).toEqual({
      idToken: 'id-token-abc',
      mode: 'refresh',
      space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/sales/2026/', database: 'alice'},
      tableName: 'sales_2026',
      // A refresh reconstructs the table's existing keys — it never redeclares them.
      partitionKeys: [],
      requestId: cmd.input.MessageDeduplicationId
    });
  });

  it('omits allowRemovals entirely unless the opt-in was ticked', async () => {
    const {send} = fakeQueue();
    await enqueueTableRefresh({...refreshReq, allowRemovals: false});
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    // SPEC-144 validates the flag rather than coercing it: absent ≠ false.
    expect(body).not.toHaveProperty('allowRemovals');
  });

  it('includes allowRemovals when the opt-in was ticked', async () => {
    const {send} = fakeQueue();
    await enqueueTableRefresh({...refreshReq, allowRemovals: true});
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body.allowRemovals).toBe(true);
  });

  it('carries a shared space through and groups by its database', async () => {
    const {send} = fakeQueue();
    await enqueueTableRefresh({
      space: {kind: 'shared', bucket: 'dat-prod-shared-space', prefix: 'salesdata/events/', database: 'salesdata'},
      tableName: 'events'
    });
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.MessageGroupId).toBe('salesdata');
    const body = JSON.parse(cmd.input.MessageBody as string);
    expect(body.space).toEqual({
      kind: 'shared',
      bucket: 'dat-prod-shared-space',
      prefix: 'salesdata/events/',
      database: 'salesdata'
    });
  });

  it('never puts a client-asserted actor in the body (only the ID token)', async () => {
    const {send} = fakeQueue();
    await enqueueTableRefresh(refreshReq);
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body).not.toHaveProperty('actor');
    expect(body).not.toHaveProperty('username');
  });

  it('reads the queue URL at call time, so an unset URL fails without sending', async () => {
    vi.stubEnv('VITE_TABLE_BUILD_QUEUE_URL', '');
    const {send} = fakeQueue();
    const result = await enqueueTableRefresh(refreshReq);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.message).toBe('Table refresh is not configured');
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a typed error when SendMessage fails (never throws)', async () => {
    fakeQueue({name: 'Throttling', message: 'slow down'});
    const result = await enqueueTableRefresh(refreshReq);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.code).toBe('Throttling');
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
