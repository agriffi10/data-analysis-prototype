import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueTableShare} from './tableShare.service';
import type {TableShareRequest} from './tableShare.types';

const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-table-share-requests.fifo';

type Cmd = {input: Record<string, unknown>};

function fakeQueue(rejectWith?: unknown) {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
  if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
  else send.mockResolvedValue({MessageId: 'm1'});
  mockGetSqs.mockResolvedValue({success: true, data: {send}});
  return {send};
}

const req: TableShareRequest = {
  source: {database: 'alice', table: 'orders'},
  tableName: 'orders_copy',
  recipients: [
    {kind: 'user', name: 'bob'},
    {kind: 'space', name: 'salesteam'}
  ]
};

beforeEach(() => {
  vi.stubEnv('VITE_TABLE_SHARE_QUEUE_URL', QUEUE);
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('enqueueTableShare', () => {
  it('builds the SPEC-089 envelope and sends FIFO grouped by source database.table', async () => {
    const {send} = fakeQueue();
    const result = await enqueueTableShare(req);
    expect(result.success).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.QueueUrl).toBe(QUEUE);
    expect(cmd.input.MessageGroupId).toBe('alice.orders');
    const body = JSON.parse(cmd.input.MessageBody as string);
    expect(body).toEqual({
      actor: 'id-token-abc',
      source: {database: 'alice', table: 'orders'},
      tableName: 'orders_copy',
      recipients: req.recipients
    });
  });

  it('uses a stable content-hash dedup id so a double-submit collapses (FR-001)', async () => {
    const {send} = fakeQueue();
    await enqueueTableShare(req);
    await enqueueTableShare(req);
    const [first, second] = send.mock.calls.map((c) => (c[0] as Cmd).input.MessageDeduplicationId);
    expect(first).toMatch(/^[0-9a-f]{64}$/); // SHA-256 hex — valid dedup-id charset, <128 chars
    expect(second).toBe(first);
  });

  it('varies the dedup id when the request differs', async () => {
    const {send} = fakeQueue();
    await enqueueTableShare(req);
    await enqueueTableShare({...req, tableName: 'other_name'});
    const [first, second] = send.mock.calls.map((c) => (c[0] as Cmd).input.MessageDeduplicationId);
    expect(second).not.toBe(first);
  });

  it('ignores recipient order in the dedup id', async () => {
    const {send} = fakeQueue();
    await enqueueTableShare(req);
    await enqueueTableShare({...req, recipients: [...req.recipients].reverse()});
    const [first, second] = send.mock.calls.map((c) => (c[0] as Cmd).input.MessageDeduplicationId);
    expect(second).toBe(first);
  });

  it('never puts a client-asserted username in the body (only the ID token)', async () => {
    const {send} = fakeQueue();
    await enqueueTableShare(req);
    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body).not.toHaveProperty('username');
    expect(body.actor).toBe('id-token-abc');
  });

  it('fails when the queue URL is not configured', async () => {
    vi.stubEnv('VITE_TABLE_SHARE_QUEUE_URL', '');
    const {send} = fakeQueue();
    const result = await enqueueTableShare(req);
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('propagates an ID-token failure without sending', async () => {
    const {send} = fakeQueue();
    mockGetIdToken.mockResolvedValue({success: false, error: {message: 'no token'}});
    const result = await enqueueTableShare(req);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.message).toBe('no token');
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a typed error when SendMessage fails', async () => {
    fakeQueue({name: 'Throttling', message: 'slow down'});
    const result = await enqueueTableShare(req);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.code).toBe('Throttling');
  });
});
