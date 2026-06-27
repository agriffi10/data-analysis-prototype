import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type MockedFunction,
} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({ getSqsClient: vi.fn() }));
vi.mock('../../lib/s3Client', () => ({ getS3Client: vi.fn() }));
vi.mock('../../lib/awsCredentials', () => ({ getIdToken: vi.fn() }));

import { getSqsClient } from '../../lib/sqsClient';
import { getS3Client } from '../../lib/s3Client';
import { getIdToken } from '../../lib/awsCredentials';
import {
  enqueueSharedSpaceRequest,
  readSharedConnectionsCache,
} from './sharedSpaces.service';

const mockGetClient = getSqsClient as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockGetS3 = getS3Client as unknown as MockedFunction<
  () => Promise<unknown>
>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<
  () => Promise<unknown>
>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-shared-space-requests.fifo';

type SqsCommand = { input: Record<string, unknown> };

function fakeQueue() {
  const send = vi.fn<(cmd: SqsCommand) => Promise<{ MessageId: string }>>();
  send.mockResolvedValue({ MessageId: 'm1' });
  mockGetClient.mockResolvedValue({ success: true, data: { send } });
  return { send };
}

const USER_BUCKET = 'dat-prod-user-space';

// Fake an S3 client whose GetObject returns the given body (or rejects with the
// given error). `body === null` simulates a missing object.
function fakeS3(opts: { body?: string | null; rejectWith?: unknown }) {
  const send = vi.fn();
  if (opts.rejectWith !== undefined) {
    send.mockRejectedValue(opts.rejectWith);
  } else {
    send.mockResolvedValue({
      Body:
        opts.body == null
          ? undefined
          : { transformToString: async () => opts.body },
    });
  }
  mockGetS3.mockResolvedValue({ success: true, data: { send } });
  return { send };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_SHARED_SPACE_QUEUE_URL', QUEUE);
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', USER_BUCKET);
  mockGetIdToken.mockResolvedValue({ success: true, data: 'id-token-xyz' });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('enqueueSharedSpaceRequest', () => {
  it('sends exactly one well-formed create message and returns the requestId', async () => {
    const { send } = fakeQueue();

    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 'sales_data',
    });

    expect(result.success).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);

    const input = send.mock.calls[0][0].input;
    expect(input.QueueUrl).toBe(QUEUE);
    expect(input.MessageGroupId).toBe('shared-space'); // constant -> serial intake
    const body = JSON.parse(input.MessageBody as string);
    expect(body).toMatchObject({
      schemaVersion: 1,
      action: 'create',
      actor: 'alice',
      space: 'sales_data',
      payload: {},
      idToken: 'id-token-xyz',
    });
    expect(body.requestId).toEqual(expect.any(String));
    // The dedup id is the requestId so an accidental resend is collapsed.
    expect(input.MessageDeduplicationId).toBe(body.requestId);
    if (result.success) expect(result.data.requestId).toBe(body.requestId);
  });

  it('does not trust the body actor for auth — still carries the verified idToken', async () => {
    const { send } = fakeQueue();
    await enqueueSharedSpaceRequest({ action: 'create', actor: 'alice', space: 's' });
    const body = JSON.parse(
      send.mock.calls[0][0].input.MessageBody as string,
    );
    expect(body.idToken).toBe('id-token-xyz');
  });

  it('fails (no send) when the queue URL is not configured', async () => {
    vi.stubEnv('VITE_SHARED_SPACE_QUEUE_URL', '');
    const { send } = fakeQueue();
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's',
    });
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('fails (no send) when the ID token cannot be obtained', async () => {
    mockGetIdToken.mockResolvedValue({
      success: false,
      error: { message: 'No ID token — sign in required' },
    });
    const { send } = fakeQueue();
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's',
    });
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a ServiceResult error (never throws) when SendMessage fails', async () => {
    const send = vi.fn<(cmd: SqsCommand) => Promise<never>>();
    send.mockRejectedValue(
      Object.assign(new Error('network'), { name: 'NetworkError' }),
    );
    mockGetClient.mockResolvedValue({ success: true, data: { send } });
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's',
    });
    expect(result).toEqual({
      success: false,
      error: { message: 'network', code: 'NetworkError' },
    });
  });
});

describe('readSharedConnectionsCache (SPEC-052)', () => {
  it('reads the per-user cache key and returns its valid entries', async () => {
    const cache = {
      version: 1,
      connections: [
        { name: 'sales', role: 'owner', status: 'active' },
        { name: 'ops', role: 'member', status: 'provisioning' },
      ],
    };
    const { send } = fakeS3({ body: JSON.stringify(cache) });

    const result = await readSharedConnectionsCache('alice');

    expect(result).toEqual({ success: true, data: cache });
    const input = send.mock.calls[0][0].input;
    expect(input.Bucket).toBe(USER_BUCKET);
    expect(input.Key).toBe('alice/user_settings/shared-connections.json');
  });

  it('returns the empty cache (personal-only) when the file is missing', async () => {
    fakeS3({ rejectWith: Object.assign(new Error('nope'), { name: 'NoSuchKey' }) });
    const result = await readSharedConnectionsCache('alice');
    expect(result).toEqual({ success: true, data: { version: 1, connections: [] } });
  });

  it('falls back to the empty cache when the body is malformed JSON', async () => {
    fakeS3({ body: 'not json{' });
    const result = await readSharedConnectionsCache('alice');
    expect(result).toEqual({ success: true, data: { version: 1, connections: [] } });
  });

  it('drops malformed entries but keeps the well-formed ones', async () => {
    const body = JSON.stringify({
      version: 1,
      connections: [
        { name: 'good', role: 'owner', status: 'active' },
        { name: '', role: 'owner', status: 'active' }, // empty name
        { name: 'bad-status', role: 'owner', status: 'wat' },
        { role: 'owner', status: 'active' }, // missing name
      ],
    });
    fakeS3({ body });
    const result = await readSharedConnectionsCache('alice');
    expect(result.success && result.data.connections).toEqual([
      { name: 'good', role: 'owner', status: 'active' },
    ]);
  });

  it('returns a ServiceResult error (never throws) on a non-404 read failure', async () => {
    fakeS3({
      rejectWith: Object.assign(new Error('boom'), { name: 'AccessDenied' }),
    });
    const result = await readSharedConnectionsCache('alice');
    expect(result).toEqual({
      success: false,
      error: { message: 'boom', code: 'AccessDenied' },
    });
  });
});
