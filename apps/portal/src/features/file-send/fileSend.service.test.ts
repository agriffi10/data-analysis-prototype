import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getSqsClient} from '../../lib/sqsClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueFileSend} from './fileSend.service';
import type {FileSendRequest} from './fileSend.types';

const mockGetSqs = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-file-send-requests.fifo';

type Cmd = {input: Record<string, unknown>};

function fakeQueue(rejectWith?: unknown) {
  const send = vi.fn<(cmd: Cmd) => Promise<{MessageId: string}>>();
  if (rejectWith !== undefined) send.mockRejectedValue(rejectWith);
  else send.mockResolvedValue({MessageId: 'm1'});
  mockGetSqs.mockResolvedValue({success: true, data: {send}});
  return {send};
}

/** The digest the group id must equal, computed the same way the service does. */
async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

const req: FileSendRequest = {
  requestId: 'req-abc',
  space: {kind: 'personal', name: 'alice'},
  items: [
    {kind: 'file', key: 'alice/reports/q1.csv'},
    {kind: 'folder', key: 'alice/reports/2026/'}
  ],
  recipients: [
    {kind: 'user', name: 'bob'},
    {kind: 'space', name: 'finance'}
  ]
};

beforeEach(() => {
  vi.stubEnv('VITE_FILE_SEND_QUEUE_URL', QUEUE);
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'dat-prod-user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'dat-prod-shared-space');
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-abc'});
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('enqueueFileSend', () => {
  it('builds the SPEC-164 envelope exactly', async () => {
    const {send} = fakeQueue();

    const result = await enqueueFileSend(req);

    expect(result.success).toBe(true);
    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.QueueUrl).toBe(QUEUE);
    expect(JSON.parse(cmd.input.MessageBody as string)).toEqual({
      requestId: 'req-abc',
      actor: 'id-token-abc',
      source: {
        space: {kind: 'personal', name: 'alice'},
        items: req.items
      },
      recipients: req.recipients
    });
  });

  it('puts the token at the TOP LEVEL, where the shared DLQ drain reads and redacts it', async () => {
    // Not a style point. dlq_drain._notify_one does body.get("actor") and _redacted replaces
    // TOP-LEVEL keys only, so a nested {actor: {idToken}} would notify nobody on a
    // dead-lettered send AND write the raw JWT to CloudWatch. SPEC-164's contract was
    // amended to this flat shape for exactly that reason.
    const {send} = fakeQueue();

    await enqueueFileSend(req);

    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(body.actor).toBe('id-token-abc');
    expect(typeof body.actor).toBe('string');
  });

  it('sends no field the verb would reject as unknown', async () => {
    // The verb rejects unknown top-level fields rather than ignoring them (FR-002), so the
    // producer and that allowlist have to agree. This is the browser half of that agreement.
    const {send} = fakeQueue();

    await enqueueFileSend(req);

    const body = JSON.parse((send.mock.calls[0][0] as Cmd).input.MessageBody as string);
    expect(Object.keys(body).sort()).toEqual(['actor', 'recipients', 'requestId', 'source']);
  });

  it('groups by the hashed {bucket}/{root}, never the raw path', async () => {
    const {send} = fakeQueue();

    await enqueueFileSend(req);

    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.MessageGroupId).toBe(await sha256Hex('dat-prod-user-space/alice/'));
    // SQS caps the group id at 128 characters where an S3 key reaches 1024.
    expect((cmd.input.MessageGroupId as string).length).toBeLessThanOrEqual(128);
  });

  it('resolves a shared source to the shared-space bucket, as the verb does', async () => {
    const {send} = fakeQueue();

    await enqueueFileSend({...req, space: {kind: 'shared', name: 'sales'}});

    const cmd = send.mock.calls[0][0] as Cmd;
    expect(cmd.input.MessageGroupId).toBe(await sha256Hex('dat-prod-shared-space/sales/'));
  });

  it('gives two different source spaces different groups, so they do not serialize', async () => {
    const {send} = fakeQueue();

    await enqueueFileSend(req);
    await enqueueFileSend({...req, requestId: 'req-2', space: {kind: 'shared', name: 'sales'}});

    const [first, second] = send.mock.calls.map((c) => (c[0] as Cmd).input.MessageGroupId);
    expect(first).not.toBe(second);
  });

  it('gives one source space one group across different selections, so they do serialize', async () => {
    const {send} = fakeQueue();

    await enqueueFileSend(req);
    await enqueueFileSend({...req, requestId: 'req-2', items: [{kind: 'file', key: 'alice/other.csv'}]});

    const [first, second] = send.mock.calls.map((c) => (c[0] as Cmd).input.MessageGroupId);
    expect(first).toBe(second);
  });

  it('deduplicates on the requestId, which is the only double-submit guard', async () => {
    // The queue has content-based dedup OFF, deliberately: two byte-identical sends a user
    // genuinely repeats must not be silently absorbed by a five-minute window.
    const {send} = fakeQueue();

    await enqueueFileSend(req);

    expect((send.mock.calls[0][0] as Cmd).input.MessageDeduplicationId).toBe('req-abc');
  });

  it('a resubmit with a fresh requestId is not deduplicated', async () => {
    const {send} = fakeQueue();

    await enqueueFileSend(req);
    await enqueueFileSend({...req, requestId: 'req-def'});

    const ids = send.mock.calls.map((c) => (c[0] as Cmd).input.MessageDeduplicationId);
    expect(ids).toEqual(['req-abc', 'req-def']);
  });

  it('fails with a user-safe message when the queue is not configured', async () => {
    vi.stubEnv('VITE_FILE_SEND_QUEUE_URL', '');
    const {send} = fakeQueue();

    const result = await enqueueFileSend(req);

    expect(result).toEqual({
      success: false,
      error: {message: 'Sending files is not configured', code: 'NotConfigured'}
    });
    expect(send).not.toHaveBeenCalled();
  });

  it('never sends when the ID token cannot be read', async () => {
    const {send} = fakeQueue();
    mockGetIdToken.mockResolvedValue({success: false, error: {message: 'no session'}});

    const result = await enqueueFileSend(req);

    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a failure rather than throwing when the send is rejected', async () => {
    fakeQueue(new Error('network down'));

    const result = await enqueueFileSend(req);

    expect(result.success).toBe(false);
  });
});
