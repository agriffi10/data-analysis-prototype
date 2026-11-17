import {afterEach, describe, expect, it, vi} from 'vitest';
import {endSession, loadSession, peekSession, sessionKey} from './session';
import {NOW, idToken, json, storedSession, testConfig, testDeps} from './testSupport';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A provider that answers every refresh with a fresh ID token, counting the calls. */
function provider(...tokens: string[]) {
  const answers = [...tokens];
  const fetch = vi.fn(async () => json(200, {id_token: answers.shift() ?? idToken({exp: NOW + 3600})}));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

describe('a session is read', () => {
  it('treats an item at its session expiry as absent and deletes it, whatever the TTL has done', async () => {
    const {config, store, dynamo} = testDeps();
    const {cookie, item} = storedSession({sessionExpiresAt: NOW, expiresAt: NOW});
    await store.put(item);

    const loaded = await loadSession(store, config, cookie, {forceRefresh: false}, NOW);

    expect(loaded).toEqual({status: 'absent'});
    expect(dynamo.table.has(item.pk)).toBe(false);
  });

  it('answers unavailable, never absent, when the store does not answer', async () => {
    const {config, store} = testDeps();
    vi.spyOn(store, 'get').mockRejectedValue(new Error('timed out'));
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(await loadSession(store, config, storedSession().cookie, {forceRefresh: false}, NOW)).toEqual({
      status: 'unavailable'
    });
  });

  it('serves the still-valid token when a near-expiry refresh fails, but not when the refresh was forced', async () => {
    const {config, store, dynamo} = testDeps();
    const {cookie, item} = storedSession({tokenExpiresAt: NOW + 60});
    await store.put(item);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(500, {}))
    );
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const proactive = await loadSession(store, config, cookie, {forceRefresh: false}, NOW);
    const forced = await loadSession(store, config, cookie, {forceRefresh: true}, NOW);

    expect(proactive.status === 'active' && proactive.idToken).toBe(item.idToken);
    expect(forced).toEqual({status: 'unavailable'});
    expect(dynamo.table.get(item.pk)?.idToken).toEqual({S: item.idToken});
  });
});

describe('a session serves only the client that created it', () => {
  it.each([
    ['a dev-client session, on a server configured as the production client', 'dev-client', 'server-client'],
    ['a production session, on a server configured as the dev client', 'server-client', 'dev-client']
  ])('treats %s as absent, and neither refreshes nor deletes it', async (_label, createdBy, servedBy) => {
    const {config, store} = testDeps(testConfig({clientId: servedBy}));
    // Near expiry, so a session this server owned would be refreshed on this read.
    const {cookie, item} = storedSession({idToken: idToken({aud: createdBy}), tokenExpiresAt: NOW + 10});
    await store.put(item);
    const fetch = provider();

    expect(await loadSession(store, config, cookie, {forceRefresh: true}, NOW)).toEqual({status: 'absent'});
    expect(await endSession(store, config, cookie)).toBe(true);

    expect(fetch).not.toHaveBeenCalled();
    expect(await store.get(item.pk)).toEqual(item);
  });
});

describe('two requests refresh one session at once', () => {
  it('lets both succeed, advances the version once, and gives the loser the winner token', async () => {
    const {config, store, dynamo} = testDeps();
    const {cookie, item} = storedSession({tokenExpiresAt: NOW + 60});
    await store.put(item);
    const first = idToken({exp: NOW + 3600, jti: 'first'});
    const second = idToken({exp: NOW + 3600, jti: 'second'});
    provider(first, second);

    // Both read version 0 before either writes: the first update to reach the table waits for the
    // second request's read, then each writes.
    let releaseFirst: () => void = () => undefined;
    const bothRead = new Promise<void>((resolve) => (releaseFirst = resolve));
    let updates = 0;
    dynamo.beforeUpdate.hook = async () => {
      updates += 1;
      if (updates === 1) await bothRead;
    };
    const a = loadSession(store, config, cookie, {forceRefresh: false}, NOW);
    await vi.waitFor(() => expect(updates).toBe(1));
    const b = loadSession(store, config, cookie, {forceRefresh: false}, NOW);
    await vi.waitFor(() => expect(updates).toBe(2));
    releaseFirst();
    const [loadedA, loadedB] = await Promise.all([a, b]);

    expect(loadedA.status).toBe('active');
    expect(loadedB.status).toBe('active');
    const stored = dynamo.table.get(item.pk);
    expect(stored?.version).toEqual({N: '1'});
    const winner = stored?.idToken?.S;
    expect(loadedA.status === 'active' && loadedA.idToken).toBe(winner);
    expect(loadedB.status === 'active' && loadedB.idToken).toBe(winner);
  });

  it('never brings back a session signed out between a refresh read and its write', async () => {
    const {config, store, dynamo} = testDeps();
    const {cookie, item} = storedSession({tokenExpiresAt: NOW + 60});
    await store.put(item);
    provider();
    dynamo.beforeUpdate.hook = async () => {
      dynamo.table.delete(sessionKey(cookie));
    };

    expect(await loadSession(store, config, cookie, {forceRefresh: false}, NOW)).toEqual({status: 'absent'});
    expect(dynamo.table.has(item.pk)).toBe(false);
  });
});

describe('a forced refresh that loses the write', () => {
  /** A session whose next write first loses to `racer`, a token another request stores. */
  async function losingTo(racer: (write: number) => string | undefined) {
    const deps = testDeps();
    const {cookie, item} = storedSession({idToken: idToken({iat: NOW - 3600, jti: 'start'})});
    await deps.store.put(item);
    let writes = 0;
    deps.dynamo.beforeUpdate.hook = async () => {
      writes += 1;
      const racing = racer(writes);
      if (racing === undefined) return;
      const current = deps.dynamo.table.get(item.pk);
      const version = String(Number(current?.version?.N) + 1);
      deps.dynamo.table.set(item.pk, {...current, idToken: {S: racing}, version: {N: version}});
    };
    return {...deps, cookie, item, writes: () => writes};
  }
  const forced = idToken({iat: NOW, jti: 'forced'});

  it('stores its own token when the token it lost to was issued earlier', async () => {
    const {config, store, dynamo, cookie, item, writes} = await losingTo((write) =>
      write === 1 ? idToken({iat: NOW - 1, jti: 'older'}) : undefined
    );
    provider(forced);

    const loaded = await loadSession(store, config, cookie, {forceRefresh: true}, NOW);

    expect(loaded.status === 'active' && loaded.idToken).toBe(forced);
    expect(dynamo.table.get(item.pk)?.idToken).toEqual({S: forced});
    expect(writes()).toBe(2);
  });

  it('uses the stored token, and writes no more, when it was issued in the same second or later', async () => {
    for (const iat of [NOW, NOW + 1]) {
      const same = idToken({iat, jti: `stored-${iat}`});
      const {config, store, dynamo, cookie, item, writes} = await losingTo((write) => (write === 1 ? same : undefined));
      provider(forced);

      const loaded = await loadSession(store, config, cookie, {forceRefresh: true}, NOW);

      expect(loaded.status === 'active' && loaded.idToken).toBe(same);
      expect(dynamo.table.get(item.pk)?.idToken).toEqual({S: same});
      expect(writes()).toBe(1);
    }
  });

  it('answers unavailable after exactly five writes when every one loses to an earlier token', async () => {
    const {config, store, cookie, writes} = await losingTo(() => idToken({iat: NOW - 1, jti: 'older'}));
    provider(forced);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(await loadSession(store, config, cookie, {forceRefresh: true}, NOW)).toEqual({status: 'unavailable'});
    expect(writes()).toBe(5);
  });
});

describe('the server keeps no session in memory', () => {
  it('finds a session it has just served only through the store it is given', async () => {
    const {config, store} = testDeps();
    const {cookie, item} = storedSession();
    await store.put(item);
    expect((await loadSession(store, config, cookie, {forceRefresh: false}, NOW)).status).toBe('active');

    const emptyStore = testDeps(testConfig()).store;

    expect(await loadSession(emptyStore, config, cookie, {forceRefresh: false}, NOW)).toEqual({status: 'absent'});
    expect((await loadSession(store, config, cookie, {forceRefresh: false}, NOW)).status).toBe('active');
  });
});

describe('a session is peeked', () => {
  it('serves a token inside the refresh margin as found, with no provider call and no store write', async () => {
    const {config, store, dynamo} = testDeps();
    const {cookie, item} = storedSession({tokenExpiresAt: NOW + 120});
    await store.put(item);
    dynamo.sent.length = 0;
    const fetch = provider();

    const peeked = await peekSession(store, config, cookie, NOW);

    expect(peeked).toEqual({status: 'active', idToken: item.idToken, tokenExpiresAt: NOW + 120});
    expect(fetch).not.toHaveBeenCalled();
    expect(dynamo.sent.map(({name}) => name)).toEqual(['GetItemCommand']);
  });

  it.each([
    ['a stored token that has expired', {tokenExpiresAt: NOW}],
    ['a token that names no user', {idToken: idToken({'cognito:username': undefined})}],
    ['a session another client created', {idToken: idToken({aud: 'another-client'})}],
    ['a session past its own expiry', {sessionExpiresAt: NOW, expiresAt: NOW}]
  ])('answers none for %s, and leaves the item where it was', async (_case, overrides) => {
    const {config, store, dynamo} = testDeps();
    const {cookie, item} = storedSession(overrides);
    await store.put(item);
    dynamo.sent.length = 0;
    const fetch = provider();

    expect(await peekSession(store, config, cookie, NOW)).toEqual({status: 'none'});
    expect(fetch).not.toHaveBeenCalled();
    expect(dynamo.sent.map(({name}) => name)).toEqual(['GetItemCommand']);
    expect(dynamo.table.has(item.pk)).toBe(true);
  });

  it('answers none, after one log line, when the store does not answer', async () => {
    const {config, store} = testDeps();
    vi.spyOn(store, 'get').mockRejectedValue(new Error('timed out'));
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(await peekSession(store, config, storedSession().cookie, NOW)).toEqual({status: 'none'});
    expect(error).toHaveBeenCalledTimes(1);
  });
});
