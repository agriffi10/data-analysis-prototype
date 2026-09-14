import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

import {apiRequest} from '../../lib/apiClient';
import {apiFailure, mockApi} from '../../test/apiMock';
import type {ApiMock} from '../../test/apiMock';
import {getNotifications, enqueueNotificationAction} from './notifications.service';
import type {Notification} from './notifications.types';

const mockApiRequest = vi.mocked(apiRequest);

const USER = 'alice';
const BUCKET = 'dat-prod-user-space';

// Fake the document route. `body === null` is an absent object, which the route reports as
// NotFound and the reader turns into the empty feed — absence has nothing to lose. `failWith` is
// a machine code, since a failure now arrives as a code rather than as a thrown AWS error.
function fakeS3(opts: {body?: string | null; failWith?: string}) {
  const send = mockApiRequest;
  send.mockImplementation(async () => {
    if (opts.failWith !== undefined) return {success: false, error: {message: '', code: opts.failWith}};
    if (opts.body == null) return {success: false, error: {message: '', code: 'NotFound'}};
    return {success: true, data: {body: opts.body, etag: 'e'}};
  });
  return {send};
}

const note = (over: Partial<Notification>): Notification => ({
  id: 'n1',
  message: 'hello',
  read: false,
  timestamp: '2026-06-28T00:00:00.000Z',
  ...over
});

beforeEach(() => {
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', BUCKET);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe('getNotifications', () => {
  it('reads from the per-user inbox key', async () => {
    const {send} = fakeS3({body: '[]'});
    await getNotifications(USER);
    expect(send).toHaveBeenCalledTimes(1);
    // The bucket no longer travels — the API resolves the space from the caller's claims — so the
    // key and the derived space are what remain observable, and they are what this always meant.
    expect(send.mock.calls[0][0]).toBe('objects.readContent');
    expect(send.mock.calls[0][1]).toMatchObject({
      query: {spaceKind: 'personal', spaceName: 'alice', key: 'alice/user_settings/notifications.json'}
    });
  });

  it('returns rows newest-first', async () => {
    const older = note({id: 'old', timestamp: '2026-06-01T00:00:00.000Z'});
    const newer = note({id: 'new', timestamp: '2026-06-27T00:00:00.000Z'});
    fakeS3({body: JSON.stringify([older, newer])});
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.map((n) => n.id)).toEqual(['new', 'old']);
  });

  it('coerces a missing/odd read flag to a boolean', async () => {
    fakeS3({body: JSON.stringify([{id: 'a', message: 'm', timestamp: '2026-06-27T00:00:00.000Z'}])});
    const result = await getNotifications(USER);
    expect(result.success && result.data[0].read).toBe(false);
  });

  it('carries a link through to the reader, and drops a non-string one (SPEC-113 FR-008)', async () => {
    // `normalize` rebuilds each row field-by-field, so a field it doesn't name is
    // silently discarded. Without this test, dropping `link` there would make every
    // deep link vanish between S3 and the row with the whole suite still green —
    // the notification would arrive and simply not be clickable.
    fakeS3({
      body: JSON.stringify([
        note({id: 'linked', link: '/data-quality/alice/req-1'}),
        note({id: 'plain'}),
        {...note({id: 'bad-type'}), link: 42}
      ])
    });
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (!result.success) return;
    const byId = Object.fromEntries(result.data.map((n) => [n.id, n]));
    expect(byId.linked.link).toBe('/data-quality/alice/req-1');
    expect(byId.plain).not.toHaveProperty('link');
    expect(byId['bad-type']).not.toHaveProperty('link');
  });

  it('carries a payload through, and drops one whose request id could change a URL', async () => {
    // Same rule the link follows and the same reason for pinning it: `normalize` rebuilds each
    // row field-by-field, so a field it does not name vanishes between S3 and the row with the
    // whole suite still green. Here that would present as an operation whose conflicts are
    // unreachable for anyone who closed the submitting tab.
    //
    // The id is shape-checked because the row interpolates it into a URL. A row carrying a bad
    // one still ARRIVES — only the field is dropped.
    const payload = {requestId: '11111111-2222-3333-4444-555555555555', operation: 'move'};
    fakeS3({
      body: JSON.stringify([
        note({id: 'carried', payload}),
        note({id: 'plain'}),
        {...note({id: 'not-an-object'}), payload: 'req-1'},
        {...note({id: 'an-array'}), payload: [payload]},
        {...note({id: 'no-id'}), payload: {operation: 'move'}},
        {...note({id: 'hostile-id'}), payload: {requestId: 'a&b=c'}}
      ])
    });
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (!result.success) return;
    const byId = Object.fromEntries(result.data.map((n) => [n.id, n]));
    expect(byId.carried.payload).toEqual(payload);
    for (const id of ['plain', 'not-an-object', 'an-array', 'no-id', 'hostile-id']) {
      expect(byId[id]).not.toHaveProperty('payload');
      expect(byId[id]).toBeDefined();
    }
  });

  it('rebuilds the payload field-by-field, dropping entries that promise more than they carry', async () => {
    // The declared type is a promise nobody checked: this is untrusted data, on a queue the portal
    // role can write to. Carried through unexamined, `conflicts` could be a string or an array of
    // nulls and still type as `NotificationConflict[]` to the reader that renders those fields.
    // Deliberately typed `unknown`: this is what ARRIVES, not what the type says arrives, and the
    // whole point of the rebuild is that the two are different things.
    const hostile: unknown = {
      requestId: '11111111-2222-3333-4444-555555555555',
      operation: 'move',
      source: {kind: 'personal', name: 'alice', junk: 1},
      destination: 'not-an-object',
      conflicts: [{itemKey: 'alice/a.csv', kind: 'file', sample: ['out/a.csv', 42]}, {kind: 'file'}, null, 'a string']
    };
    fakeS3({body: JSON.stringify([{...note({id: 'mixed'}), payload: hostile}])});
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (!result.success) return;
    const {payload} = result.data[0];
    expect(payload?.source).toEqual({kind: 'personal', name: 'alice'});
    expect(payload).not.toHaveProperty('destination');
    expect(payload?.conflicts).toEqual([{itemKey: 'alice/a.csv', kind: 'file', sample: ['out/a.csv']}]);
    // Three entries went in and one came out, so the list on screen is NOT the whole list.
    expect(payload?.more).toBe(true);
  });

  it('normalises a row written before the payload field byte-identically', async () => {
    // The reader half of "a row lacking the field is unchanged and valid". Six other planes write
    // rows and none of them was modified, so every notification already sitting in an inbox has
    // to come back exactly as it did before.
    const before = {id: 'old', message: 'Table created', read: true, timestamp: '2026-01-01T00:00:00.000Z'};
    fakeS3({body: JSON.stringify([before])});
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(JSON.stringify(result.data[0])).toBe(JSON.stringify(before));
  });

  it('drops malformed rows but keeps valid ones', async () => {
    fakeS3({body: JSON.stringify([{nope: true}, note({id: 'ok'})])});
    const result = await getNotifications(USER);
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.map((n) => n.id)).toEqual(['ok']);
  });

  it('treats a 404 (missing inbox) as the empty state', async () => {
    fakeS3({failWith: 'NotFound'});
    const result = await getNotifications(USER);
    expect(result).toEqual({success: true, data: []});
  });

  it('treats corrupt JSON as empty', async () => {
    fakeS3({body: '{not json'});
    const result = await getNotifications(USER);
    expect(result).toEqual({success: true, data: []});
  });

  it('treats a non-array root as empty', async () => {
    fakeS3({body: JSON.stringify({version: 1})});
    const result = await getNotifications(USER);
    expect(result).toEqual({success: true, data: []});
  });

  it('surfaces any other S3 error', async () => {
    fakeS3({failWith: 'AccessDenied'});
    const result = await getNotifications(USER);
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.code).toBe('AccessDenied');
  });
});

/**
 * The notifications enqueue, now over the API.
 *
 * **The FIFO group id is deliberately absent from this file.** It was the caller-supplied
 * username, and that is precisely what changed in the move: the API groups on the VERIFIED actor
 * and ignores a `username` in the body, asserted against a body that carries someone else's in
 * `lambdas/api/test_fifo_derivations.py`. The dedup id — the one id this plane mints, fresh every
 * time, because a mark-read is idempotent and must never be absorbed — has its own test there
 * too, and no token rides in the body: the API stamps the verified caller as the identity block.
 *
 * The `username` argument stays on this service's input because its callers pass it and the query
 * keys read it; it simply no longer reaches the wire.
 */
describe('enqueueNotificationAction', () => {
  let api: ApiMock;

  beforeEach(() => {
    api = mockApi(mockApiRequest);
  });

  it('sends the action and the id it applies to, exactly once', async () => {
    api.on('notifications.enqueue', {success: true, data: {requestId: null}});

    const result = await enqueueNotificationAction({action: 'markRead', username: USER, id: 'n9'});

    expect(result).toEqual({success: true, data: undefined});
    expect(api.routes()).toEqual(['notifications.enqueue']);
    // `toEqual`, not `toMatchObject`: that no client-asserted username rides along is the
    // assertion, and the API refuses a body claiming an identity outright.
    expect(api.bodyFor('notifications.enqueue')).toEqual({action: 'markRead', id: 'n9'});
  });

  it('sends markAllRead with an explicit null id, because the field cannot be defaulted', async () => {
    // The contract declares `id` as `string | null` rather than optional: a wire vocabulary with
    // no optional field would otherwise make an omitted id and a forgotten one the same request.
    api.on('notifications.enqueue', {success: true, data: {requestId: null}});

    const result = await enqueueNotificationAction({action: 'markAllRead', username: USER});

    expect(result).toEqual({success: true, data: undefined});
    expect(api.bodyFor('notifications.enqueue')).toEqual({action: 'markAllRead', id: null});
  });

  it('rejects markRead without an id and calls nothing', async () => {
    // Still refused in the browser: a markRead with no id is a request the writer cannot act on,
    // and refusing it here is what keeps the failure attributable to the gesture that made it.
    const result = await enqueueNotificationAction({action: 'markRead', username: USER});

    expect(result.success === false && result.error.code).toBe('InvalidRequest');
    expect(api.calls).toEqual([]);
  });

  it('returns the failure as a result and never throws', async () => {
    api.on('notifications.enqueue', apiFailure('RateLimited'));

    const result = await enqueueNotificationAction({action: 'markAllRead', username: USER});

    expect(result.success).toBe(false);
    expect(result.success === false && result.error.code).toBe('RateLimited');
  });
});
