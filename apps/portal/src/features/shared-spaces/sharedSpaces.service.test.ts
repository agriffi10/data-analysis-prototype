import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';

vi.mock('../../lib/sqsClient', () => ({getSqsClient: vi.fn()}));
vi.mock('../../lib/apiClient', () => ({apiRequest: vi.fn()}));
vi.mock('../../lib/awsCredentials', () => ({getIdToken: vi.fn()}));

import {getSqsClient} from '../../lib/sqsClient';
import {apiRequest} from '../../lib/apiClient';
import {getIdToken} from '../../lib/awsCredentials';
import {enqueueSharedSpaceRequest, readSharedConnectionsCache} from './sharedSpaces.service';

const mockGetClient = getSqsClient as unknown as MockedFunction<() => Promise<unknown>>;
const mockGetIdToken = getIdToken as unknown as MockedFunction<() => Promise<unknown>>;

const QUEUE = 'https://sqs.us-east-1.amazonaws.com/123/dat-prod-shared-space-requests.fifo';

type SqsCommand = {input: Record<string, unknown>};

function fakeQueue() {
  const send = vi.fn<(cmd: SqsCommand) => Promise<{MessageId: string}>>();
  send.mockResolvedValue({MessageId: 'm1'});
  mockGetClient.mockResolvedValue({success: true, data: {send}});
  return {send};
}

const USER_BUCKET = 'dat-prod-user-space';

// Fake the document route. `body === null` is an absent object, which the route reports as
// NotFound; `failWith` is a machine code, since a failure now arrives as a code rather than as a
// thrown AWS error.
function fakeS3(opts: {body?: string | null; failWith?: string}) {
  const send = vi.mocked(apiRequest);
  send.mockImplementation(async () => {
    if (opts.failWith !== undefined) return {success: false, error: {message: '', code: opts.failWith}};
    if (opts.body == null) return {success: false, error: {message: '', code: 'NotFound'}};
    return {success: true, data: {body: opts.body, etag: 'e'}};
  });
  return {send};
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('VITE_SHARED_SPACE_QUEUE_URL', QUEUE);
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', USER_BUCKET);
  mockGetIdToken.mockResolvedValue({success: true, data: 'id-token-xyz'});
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('enqueueSharedSpaceRequest', () => {
  it('sends exactly one well-formed create message and returns the requestId', async () => {
    const {send} = fakeQueue();

    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 'sales_data'
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
      idToken: 'id-token-xyz'
    });
    expect(body.requestId).toEqual(expect.any(String));
    // The dedup id is the requestId so an accidental resend is collapsed.
    expect(input.MessageDeduplicationId).toBe(body.requestId);
    if (result.success) expect(result.data.requestId).toBe(body.requestId);
  });

  it('does not trust the body actor for auth — still carries the verified idToken', async () => {
    const {send} = fakeQueue();
    await enqueueSharedSpaceRequest({action: 'create', actor: 'alice', space: 's'});
    const body = JSON.parse(send.mock.calls[0][0].input.MessageBody as string);
    expect(body.idToken).toBe('id-token-xyz');
  });

  it('fails (no send) when the queue URL is not configured', async () => {
    vi.stubEnv('VITE_SHARED_SPACE_QUEUE_URL', '');
    const {send} = fakeQueue();
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's'
    });
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('fails (no send) when the ID token cannot be obtained', async () => {
    mockGetIdToken.mockResolvedValue({
      success: false,
      error: {message: 'No ID token — sign in required'}
    });
    const {send} = fakeQueue();
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's'
    });
    expect(result.success).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it('returns a ServiceResult error (never throws) when SendMessage fails', async () => {
    const send = vi.fn<(cmd: SqsCommand) => Promise<never>>();
    send.mockRejectedValue(Object.assign(new Error('network'), {name: 'NetworkError'}));
    mockGetClient.mockResolvedValue({success: true, data: {send}});
    const result = await enqueueSharedSpaceRequest({
      action: 'create',
      actor: 'alice',
      space: 's'
    });
    expect(result).toEqual({
      success: false,
      error: {message: 'network', code: 'NetworkError'}
    });
  });
});

describe('readSharedConnectionsCache (SPEC-052)', () => {
  it('reads the per-user cache key and returns its valid entries', async () => {
    const cache = {
      version: 1,
      connections: [
        {name: 'sales', role: 'owner', status: 'active'},
        {name: 'ops', role: 'member', status: 'provisioning'}
      ]
    };
    const {send} = fakeS3({body: JSON.stringify(cache)});

    const result = await readSharedConnectionsCache('alice');

    expect(result).toEqual({success: true, data: cache});
    // The bucket no longer travels: the API resolves the space from the caller's verified claims,
    // so what remains observable is the key and the space derived from it.
    expect(send.mock.calls[0][0]).toBe('objects.readContent');
    expect(send.mock.calls[0][1]).toMatchObject({
      query: {spaceKind: 'personal', spaceName: 'alice', key: 'alice/user_settings/shared-connections.json'}
    });
  });

  it('returns the empty cache (personal-only) when the file is missing', async () => {
    fakeS3({failWith: 'NotFound'});
    const result = await readSharedConnectionsCache('alice');
    expect(result).toEqual({success: true, data: {version: 1, connections: []}});
  });

  it('falls back to the empty cache when the body is malformed JSON', async () => {
    fakeS3({body: 'not json{'});
    const result = await readSharedConnectionsCache('alice');
    expect(result).toEqual({success: true, data: {version: 1, connections: []}});
  });

  it('drops malformed entries but keeps the well-formed ones', async () => {
    const body = JSON.stringify({
      version: 1,
      connections: [
        {name: 'good', role: 'owner', status: 'active'},
        {name: '', role: 'owner', status: 'active'}, // empty name
        {name: 'bad-status', role: 'owner', status: 'wat'},
        {role: 'owner', status: 'active'} // missing name
      ]
    });
    fakeS3({body});
    const result = await readSharedConnectionsCache('alice');
    expect(result.success && result.data.connections).toEqual([{name: 'good', role: 'owner', status: 'active'}]);
  });

  it('normalizes the owner projection members to {username, status} (SPEC-073)', async () => {
    const body = JSON.stringify({
      version: 1,
      connections: [
        {
          name: 'sales',
          role: 'owner',
          status: 'active',
          members: [
            {username: 'alice', status: 'active'},
            {username: 'bob', status: 'pending'}
          ]
        }
      ]
    });
    fakeS3({body});
    const result = await readSharedConnectionsCache('alice');
    expect(result.success && result.data.connections[0].members).toEqual([
      {username: 'alice', status: 'active'},
      {username: 'bob', status: 'pending'}
    ]);
  });

  it('reads a legacy string[] members projection as all-active, dropping malformed entries (FR-005)', async () => {
    const body = JSON.stringify({
      version: 1,
      connections: [
        {name: 'sales', role: 'owner', status: 'active', members: ['alice', 'bob', '', 42, {status: 'pending'}]}
      ]
    });
    fakeS3({body});
    const result = await readSharedConnectionsCache('alice');
    // Bare strings -> active; '' / non-string / no-username entries dropped.
    expect(result.success && result.data.connections[0].members).toEqual([
      {username: 'alice', status: 'active'},
      {username: 'bob', status: 'active'}
    ]);
  });

  it('degrades a malformed non-array members field to undefined (no crash)', async () => {
    const body = JSON.stringify({
      version: 1,
      connections: [{name: 'sales', role: 'owner', status: 'active', members: 'garbage'}]
    });
    fakeS3({body});
    const result = await readSharedConnectionsCache('alice');
    expect(result.success && result.data.connections[0].members).toBeUndefined();
  });

  it('returns a ServiceResult error (never throws) on a non-404 read failure', async () => {
    fakeS3({
      failWith: 'AccessDenied'
    });
    const result = await readSharedConnectionsCache('alice');
    // The message is the SERVICE's own wording now, not the AWS exception's: the API returns a
    // machine code and no prose, and `toUserMessage` picks the sentence from the code.
    expect(result).toMatchObject({success: false, error: {code: 'AccessDenied'}});
    expect(result.success === false && result.error.message).toBeTruthy();
  });
});
