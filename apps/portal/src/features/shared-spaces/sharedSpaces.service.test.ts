import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {mockApi, apiFailure} from '../../test/apiMock';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

import {apiRequest} from '../../lib/apiClient';
import {enqueueSharedSpaceRequest, readSharedConnectionsCache} from './sharedSpaces.service';

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
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', USER_BUCKET);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('a transfer request (SPEC-208 FR-006)', () => {
  it('sends exactly one message, naming the action and the target in the payload', async () => {
    const api = mockApi(vi.mocked(apiRequest));
    api.on('sharedSpace.enqueue', {success: true, data: {requestId: 'echoed'}});

    const result = await enqueueSharedSpaceRequest({
      action: 'transfer_ownership',
      actor: 'alice',
      space: 'salesdata',
      payload: {newOwner: 'bob'}
    });

    expect(apiRequest).toHaveBeenCalledTimes(1);
    const [route, options] = vi.mocked(apiRequest).mock.calls[0];
    expect(route).toBe('sharedSpace.enqueue');
    expect(options?.body).toMatchObject({
      action: 'transfer_ownership',
      space: 'salesdata',
      payload: {newOwner: 'bob'}
    });
    // The browser sends no actor and no token: the API stamps the identity it verified, and a
    // body supplying one is refused at the door.
    expect(options?.body).not.toHaveProperty('actor');
    expect(options?.body).not.toHaveProperty('idToken');
    expect(result.success).toBe(true);
  });
});

describe('enqueueSharedSpaceRequest', () => {
  // The envelope's server-side half — the verified actor, the advisory `actor` username, the
  // schema version and the constant FIFO group — is asserted in `lambdas/api/test_enqueue_routes.py`
  // and `test_fifo_derivations.py`, where it is now built. What is left here is the browser's
  // half: one call, the right route, the caller's own fields, and a failure that comes back as a
  // result rather than a throw.
  it('mints a request id, sends one request, and returns the id it minted', async () => {
    const api = mockApi(vi.mocked(apiRequest));
    api.on('sharedSpace.enqueue', {success: true, data: {requestId: 'echoed'}});

    const result = await enqueueSharedSpaceRequest({
      action: 'add_members',
      actor: 'alice',
      space: 'salesteam',
      payload: {members: ['bob']}
    });

    expect(api.routes()).toEqual(['sharedSpace.enqueue']);
    const body = api.bodyFor('sharedSpace.enqueue') as {requestId: string; actor?: unknown};
    expect(body).toMatchObject({
      action: 'add_members',
      space: 'salesteam',
      payload: {members: ['bob']}
    });
    // The actor is the API's to stamp from the verified bearer, and a body carrying one is
    // refused at the door — so the service must not send the one its caller passes it.
    expect(body.actor).toBeUndefined();
    expect(result).toEqual({success: true, data: {requestId: body.requestId}});
  });

  it('returns the failure as a result and never throws', async () => {
    const api = mockApi(vi.mocked(apiRequest));
    api.on('sharedSpace.enqueue', apiFailure('ApiUnavailable'));

    const result = await enqueueSharedSpaceRequest({action: 'create', actor: 'alice', space: 'x'});

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('ApiUnavailable');
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
    expect(send).toHaveBeenCalledTimes(1);
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
