import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueQualityCheck} from './dataQuality.service';
import type {DataQualityRequest} from './dataQuality.types';

const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-data-quality-requests.fifo';
const REQUEST_ID = '11111111-2222-4333-8444-555555555555';

type Cmd = {input: Record<string, unknown>};

function fakeQueue(rejectWith?: unknown) {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
  if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
  else send.mockResolvedValue({MessageId: 'm1'});
  mockGetSqs.mockResolvedValue({success: true, data: {send}});
  return {send};
}

function makeReq(over: Partial<DataQualityRequest> = {}): DataQualityRequest {
  return {
    requestId: REQUEST_ID,
    space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/'},
    location: 'alice/sales/',
    ...over
  };
}

beforeEach(() => {
  vi.stubEnv('VITE_DATA_QUALITY_QUEUE_URL', QUEUE);
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('enqueueQualityCheck', () => {
  it('sends the envelope with the token and no username', async () => {
    const {send} = fakeQueue();
    const res = await enqueueQualityCheck(makeReq());

    expect(res).toEqual({success: true, data: {requestId: REQUEST_ID}});
    const input = send.mock.calls[0][0].input;
    expect(input.QueueUrl).toBe(QUEUE);
    const body = JSON.parse(input.MessageBody as string);
    expect(body).toEqual({
      requestId: REQUEST_ID,
      idToken: 'id-token-abc',
      space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/'},
      location: 'alice/sales/'
    });
    // The actor is derived server-side from the verified claim — the body must not
    // carry an identity the caller could assert.
    expect(body).not.toHaveProperty('actor');
    expect(body).not.toHaveProperty('username');
  });

  it('uses the requestId as the deduplication id', async () => {
    const {send} = fakeQueue();
    await enqueueQualityCheck(makeReq());
    expect(send.mock.calls[0][0].input.MessageDeduplicationId).toBe(REQUEST_ID);
  });

  it('hashes a location far longer than SQS allows into a 64-char group id', async () => {
    // The failure this prevents: SQS caps MessageGroupId at 128 chars while S3 keys reach
    // 1024, so a RAW location group id would fail the send in the browser — for exactly
    // the users with the deepest folders.
    const deep = `alice/${'nested-folder/'.repeat(20)}data/`;
    expect(deep.length).toBeGreaterThan(128);

    const {send} = fakeQueue();
    const res = await enqueueQualityCheck(makeReq({location: deep}));

    expect(res.success).toBe(true);
    const groupId = send.mock.calls[0][0].input.MessageGroupId as string;
    expect(groupId).toHaveLength(64);
    expect(groupId).toMatch(/^[0-9a-f]{64}$/);
    expect(groupId).not.toContain('nested-folder');
  });

  it('gives the same group id to the same location (they serialize)', async () => {
    const {send} = fakeQueue();
    await enqueueQualityCheck(makeReq({requestId: 'req-a'}));
    await enqueueQualityCheck(makeReq({requestId: 'req-b'}));

    const [a, b] = send.mock.calls.map((c) => c[0].input.MessageGroupId);
    expect(a).toBe(b);
  });

  it('gives different group ids to different locations (they run in parallel)', async () => {
    const {send} = fakeQueue();
    await enqueueQualityCheck(makeReq({location: 'alice/sales/'}));
    await enqueueQualityCheck(makeReq({location: 'alice/marketing/'}));

    const [a, b] = send.mock.calls.map((c) => c[0].input.MessageGroupId);
    expect(a).not.toBe(b);
  });

  it('treats trailing-slash variants of one location as the same group', async () => {
    const {send} = fakeQueue();
    await enqueueQualityCheck(makeReq({location: 'alice/sales/'}));
    await enqueueQualityCheck(makeReq({location: 'alice/sales'}));

    const [a, b] = send.mock.calls.map((c) => c[0].input.MessageGroupId);
    expect(a).toBe(b);
  });

  it('returns a failure when the queue is not configured', async () => {
    vi.stubEnv('VITE_DATA_QUALITY_QUEUE_URL', '');
    const res = await enqueueQualityCheck(makeReq());
    expect(res.success).toBe(false);
  });

  it('propagates a credential failure without sending', async () => {
    mockGetIdToken.mockResolvedValue({success: false, error: {message: 'no session'}});
    const {send} = fakeQueue();
    const res = await enqueueQualityCheck(makeReq());
    expect(res.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('never throws when the send fails', async () => {
    fakeQueue(Object.assign(new Error('SQS down'), {name: 'ServiceUnavailable'}));
    const res = await enqueueQualityCheck(makeReq());
    expect(res.success).toBe(false);
    if (!res.success) expect(res.error.code).toBe('ServiceUnavailable');
  });
});
