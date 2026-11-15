import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {API_ERROR_CODES} from '../../types/apiContract.generated';
import {SESSION_COOKIE, SIGNIN_COOKIE, parseSignin, signinCookie} from './cookies';
import {api, callback, login, logout, refresh, route, session} from './handlers';
import {codeChallenge} from './oidc';
import {sessionKey} from './session';
import {API, NOW, PORTAL, idToken, json, storedSession, testConfig, testDeps} from './testSupport';

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW * 1000);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const TRANSACTION = {state: 's'.repeat(43), codeVerifier: 'v'.repeat(43), nonce: 'n'.repeat(43)};

/**
 * A request to the portal, with the given cookies and headers. A request to `/api/` names the tab's
 * user as alice, the stored session's user, unless the test names another or, with null, none.
 */
function request(
  path: string,
  init: {
    method?: string;
    cookies?: Record<string, string>;
    headers?: Record<string, string>;
    body?: BodyInit;
    tabUser?: string | null;
  } = {}
) {
  const headers = new Headers(init.headers);
  const tabUser = init.tabUser === undefined ? (path.startsWith('/api/') ? 'alice' : null) : init.tabUser;
  if (tabUser !== null) headers.set('x-dq-user', tabUser);
  const cookies = Object.entries(init.cookies ?? {}).map(([name, value]) => `${name}=${value}`);
  if (cookies.length) headers.set('cookie', cookies.join('; '));
  return new Request(`${PORTAL}${path}`, {method: init.method ?? 'GET', headers, body: init.body});
}

/** A sign-in cookie's value, as `/auth/login` would have set it. */
const signinValue = () => signinCookie(TRANSACTION).split(';')[0].split('=')[1];

/** Parse every Set-Cookie a response carries. */
const setCookies = (response: Response) => response.headers.getSetCookie();

describe('GET /auth/login', () => {
  it('sets the sign-in cookie and redirects to the provider with PKCE built from it', async () => {
    const response = await login(request('/auth/login'), testDeps());

    expect(response.status).toBe(302);
    const [cookie] = setCookies(response);
    expect(cookie).toMatch(/^__Host-dq_signin=[^;]+; Path=\/; Secure; HttpOnly; SameSite=Lax; Max-Age=3600$/);
    const transaction = parseSignin(cookie.split(';')[0].split('=')[1]);
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.origin + location.pathname).toBe('https://auth.example.test/oauth2/authorize');
    expect(Object.fromEntries(location.searchParams)).toMatchObject({
      response_type: 'code',
      client_id: 'server-client',
      redirect_uri: `${PORTAL}/auth/callback`,
      state: transaction?.state,
      nonce: transaction?.nonce,
      code_challenge_method: 'S256',
      code_challenge: codeChallenge(transaction?.codeVerifier ?? '')
    });
    expect(location.searchParams.has('identity_provider')).toBe(false);
  });

  it('sends the user straight to the configured identity provider', async () => {
    const response = await login(request('/auth/login'), testDeps(testConfig({identityProvider: 'EntraID'})));

    const location = new URL(response.headers.get('location') ?? '');
    expect(location.searchParams.getAll('identity_provider')).toEqual(['EntraID']);
  });
});

describe('GET /auth/callback', () => {
  const exits = [
    {
      label: 'no sign-in cookie',
      query: `?code=c&state=${TRANSACTION.state}`,
      cookie: false,
      exchange: false,
      cleared: false
    },
    {label: 'a mismatched state', query: '?code=c&state=other', cookie: true, exchange: false, cleared: false},
    {
      label: 'a provider error',
      query: `?error=access_denied&state=${TRANSACTION.state}`,
      cookie: true,
      exchange: false,
      cleared: true
    },
    {
      label: 'a failed exchange',
      query: `?code=c&state=${TRANSACTION.state}`,
      cookie: true,
      exchange: 'refused',
      cleared: true
    },
    ...['aud', 'iss', 'token_use', 'nonce', 'exp'].map((claim) => ({
      label: `a wrong ${claim}`,
      query: `?code=c&state=${TRANSACTION.state}`,
      cookie: true,
      exchange: claim,
      cleared: true
    }))
  ];

  it.each(exits)(
    'redirects to the failure message and creates no session on $label',
    async ({query, cookie, exchange, cleared}) => {
      const wrong: Record<string, unknown> = {
        aud: 'other',
        iss: 'https://other',
        token_use: 'access',
        nonce: 'other',
        exp: NOW - 1
      };
      const fetch = vi.fn(async () =>
        exchange === 'refused'
          ? json(400, {error: 'invalid_grant'})
          : json(200, {
              id_token: idToken({nonce: TRANSACTION.nonce, [String(exchange)]: wrong[String(exchange)]}),
              refresh_token: 'r'
            })
      );
      vi.stubGlobal('fetch', fetch);
      vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const deps = testDeps();

      const response = await callback(
        request(`/auth/callback${query}`, {cookies: cookie ? {[SIGNIN_COOKIE]: signinValue()} : {}}),
        deps
      );

      expect(response.status).toBe(302);
      expect(response.headers.get('location')).toBe(`${PORTAL}/?signin=failed`);
      expect(deps.dynamo.table.size).toBe(0);
      expect(fetch).toHaveBeenCalledTimes(exchange ? 1 : 0);
      expect(setCookies(response).some((value) => value.startsWith(`${SIGNIN_COOKIE}=;`))).toBe(cleared);
    }
  );

  it('stores a session under a fresh id, replaces the one the browser had, and redirects home', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(200, {id_token: idToken({nonce: TRANSACTION.nonce}), refresh_token: 'r'}))
    );
    const deps = testDeps();
    const previous = storedSession();
    await deps.store.put(previous.item);

    const response = await callback(
      request(`/auth/callback?code=c&state=${TRANSACTION.state}`, {
        cookies: {[SIGNIN_COOKIE]: signinValue(), [SESSION_COOKIE]: previous.cookie}
      }),
      deps
    );

    expect(response.headers.get('location')).toBe(`${PORTAL}/`);
    const [session, cleared] = setCookies(response);
    expect(session).toMatch(/^__Host-dq_session=[A-Za-z0-9_-]{43}; Path=\/; Secure; HttpOnly; SameSite=Lax$/);
    const id = session.split(';')[0].split('=')[1];
    expect(id).not.toBe(previous.cookie);
    expect(cleared).toBe(`${SIGNIN_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0`);
    expect(deps.dynamo.table.has(sessionKey(id))).toBe(true);
    expect(deps.dynamo.table.has(previous.item.pk)).toBe(false);
  });

  it('leaves a replaced session in place when another client created it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(200, {id_token: idToken({nonce: TRANSACTION.nonce}), refresh_token: 'r'}))
    );
    const deps = testDeps();
    const foreign = storedSession({idToken: idToken({aud: 'dev-client'})});
    await deps.store.put(foreign.item);

    const response = await callback(
      request(`/auth/callback?code=c&state=${TRANSACTION.state}`, {
        cookies: {[SIGNIN_COOKIE]: signinValue(), [SESSION_COOKIE]: foreign.cookie}
      }),
      deps
    );

    expect(response.headers.get('location')).toBe(`${PORTAL}/`);
    expect(await deps.store.get(foreign.item.pk)).toEqual(foreign.item);
  });

  it('builds every redirect and redirect_uri from the portal origin, whatever host the request names', async () => {
    const forged = (path: string, cookies: Record<string, string> = {}) =>
      new Request(`https://evil.example${path}`, {
        headers: {
          host: 'evil.example',
          'x-forwarded-host': 'evil.example',
          cookie: Object.entries(cookies)
            .map(([name, value]) => `${name}=${value}`)
            .join('; ')
        }
      });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(200, {id_token: idToken({nonce: TRANSACTION.nonce}), refresh_token: 'r'}))
    );

    const signin = await login(forged('/auth/login'), testDeps());
    const failed = await callback(forged('/auth/callback?state=other'), testDeps());
    const signedIn = await callback(
      forged(`/auth/callback?code=c&state=${TRANSACTION.state}`, {[SIGNIN_COOKIE]: signinValue()}),
      testDeps()
    );

    expect(new URL(signin.headers.get('location') ?? '').searchParams.get('redirect_uri')).toBe(
      `${PORTAL}/auth/callback`
    );
    expect(failed.headers.get('location')).toBe(`${PORTAL}/?signin=failed`);
    expect(signedIn.headers.get('location')).toBe(`${PORTAL}/`);
    const [, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(new URLSearchParams(String(init.body)).get('redirect_uri')).toBe(`${PORTAL}/auth/callback`);
  });
});

describe('POST /auth/logout', () => {
  it('deletes the session before revoking its token, clears the cookie, and answers the logout URL', async () => {
    const deps = testDeps();
    const {cookie, item} = storedSession();
    await deps.store.put(item);
    const fetch = vi.fn(async () => {
      expect(deps.dynamo.table.has(item.pk)).toBe(false);
      return new Response(null, {status: 503});
    });
    vi.stubGlobal('fetch', fetch);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const response = await logout(
      request('/auth/logout', {method: 'POST', cookies: {[SESSION_COOKIE]: cookie}, headers: {origin: PORTAL}}),
      deps
    );

    expect(fetch).toHaveBeenCalledOnce();
    expect(response.status).toBe(200);
    const {logoutUrl} = (await response.json()) as {logoutUrl: string};
    expect(Object.fromEntries(new URL(logoutUrl).searchParams)).toEqual({
      client_id: 'server-client',
      logout_uri: PORTAL
    });
    expect(setCookies(response)).toEqual([`${SESSION_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0`]);
    const none = await logout(request('/auth/logout', {method: 'POST', headers: {origin: PORTAL}}), deps);
    expect(none.status).toBe(200);
  });
});

describe('GET /auth/session and POST /auth/refresh', () => {
  it('answers the user, and the API refusal for no cookie, a malformed one, an unknown id and an expired item', async () => {
    const deps = testDeps();
    const live = storedSession();
    await deps.store.put(live.item);
    const response = await session(request('/auth/session', {cookies: {[SESSION_COOKIE]: live.cookie}}), deps);
    expect(await response.json()).toEqual({username: 'alice', email: 'alice@example.test'});

    const expired = storedSession({sessionExpiresAt: NOW});
    const spy = vi.spyOn(deps.store, 'get');
    const refusedCookies: Record<string, string>[] = [
      {},
      {[SESSION_COOKIE]: 'short'},
      {[SESSION_COOKIE]: 'u'.repeat(43)}
    ];
    for (const cookies of refusedCookies) {
      const refused = await session(request('/auth/session', {cookies}), deps);
      expect(refused.status).toBe(401);
      expect(refused.headers.get('www-authenticate')).toBe('Bearer');
      expect(((await refused.json()) as {error: {code: string}}).error.code).toBe('SessionExpired');
    }
    expect(spy).toHaveBeenCalledOnce();
    await deps.store.put({...expired.item, pk: sessionKey('e'.repeat(43))});
    expect((await session(request('/auth/session', {cookies: {[SESSION_COOKIE]: 'e'.repeat(43)}}), deps)).status).toBe(
      401
    );
  });

  it('answers the username from the configured claim, not from cognito:username', async () => {
    const deps = testDeps(testConfig({usernameClaim: 'custom:portal_username'}));
    const federated = storedSession({
      idToken: idToken({'cognito:username': 'entraid_3f2a9c', 'custom:portal_username': 'bob'})
    });
    await deps.store.put(federated.item);

    const response = await session(request('/auth/session', {cookies: {[SESSION_COOKIE]: federated.cookie}}), deps);

    expect(await response.json()).toEqual({username: 'bob', email: 'alice@example.test'});
  });

  it('refreshes on demand, ends the session on invalid_grant, and answers 503 on a fault', async () => {
    const deps = testDeps();
    const {cookie, item} = storedSession();
    await deps.store.put(item);
    const post = () =>
      request('/auth/refresh', {method: 'POST', cookies: {[SESSION_COOKIE]: cookie}, headers: {origin: PORTAL}});
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(200, {id_token: idToken({jti: 'new'})}))
    );
    expect((await refresh(post(), deps)).status).toBe(204);

    for (const answer of [() => json(400, {error: 'invalid_client'}), () => Promise.reject(new Error('down'))]) {
      vi.stubGlobal('fetch', vi.fn(answer));
      expect((await refresh(post(), deps)).status).toBe(503);
      expect(deps.dynamo.table.has(item.pk)).toBe(true);
    }

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(400, {error: 'invalid_grant'}))
    );
    expect((await refresh(post(), deps)).status).toBe(401);
    expect(deps.dynamo.table.has(item.pk)).toBe(false);
  });
});

describe('the Origin check', () => {
  const unsafe = [
    ['/auth/logout', logout],
    ['/auth/refresh', refresh],
    ['/api/v1/x', api]
  ] as const;

  it.each(unsafe)('refuses an unsafe %s from anywhere but the portal, before any store read', async (path, handler) => {
    const deps = testDeps();
    const get = vi.spyOn(deps.store, 'get');
    for (const origin of [undefined, API, `${PORTAL}:8443`, 'null']) {
      const response = await handler(request(path, {method: 'POST', headers: origin ? {origin} : {}}), deps);
      expect(response.status).toBe(403);
    }
    expect(get).not.toHaveBeenCalled();
    expect((await handler(request(path, {method: 'POST', headers: {origin: PORTAL}}), deps)).status).not.toBe(403);
  });
});

describe('/api/<rest>', () => {
  async function signedIn(item = storedSession().item) {
    const deps = testDeps();
    await deps.store.put(item);
    return deps;
  }
  const cookies = {[SESSION_COOKIE]: storedSession().cookie};

  it('forwards to the API with the prefix removed and the session token as the only bearer', async () => {
    const deps = await signedIn();
    const fetch = vi.fn(async () =>
      json(200, {ok: true}, {'cache-control': 'no-store', 'set-cookie': 'x=1', 'x-amzn-trace': 't'})
    );
    vi.stubGlobal('fetch', fetch);

    const response = await api(
      request('/api/v1/x?y=1', {
        cookies,
        headers: {
          authorization: 'Bearer forged',
          accept: 'application/json',
          'content-type': 'application/json',
          'x-request-id': 'r1',
          'x-other': 'z'
        }
      }),
      deps
    );

    const [target, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(target).toBe(`${API}/v1/x?y=1`);
    expect(Object.fromEntries(new Headers(init.headers))).toEqual({
      accept: 'application/json',
      authorization: `Bearer ${storedSession().item.idToken}`,
      'content-type': 'application/json',
      'x-request-id': 'r1'
    });
    expect(init.redirect).toBe('manual');
    expect([...response.headers.keys()].sort()).toEqual(['cache-control', 'content-type']);
    expect(await response.json()).toEqual({ok: true});

    vi.stubGlobal('fetch', vi.fn());
    expect((await api(request('/api/v1/x'), deps)).status).toBe(401);
  });

  it('refuses a tab that names no user before reading the store, and one naming another user before forwarding', async () => {
    const deps = await signedIn(storedSession({idToken: idToken({'cognito:username': 'ana maría'})}).item);
    const get = vi.spyOn(deps.store, 'get');
    const fetch = vi.fn(async () => json(200, {}));
    vi.stubGlobal('fetch', fetch);

    const unnamed = await api(request('/api/v1/x', {cookies, tabUser: null}), deps);
    expect([unnamed.status, (await unnamed.json()).error.code, get.mock.calls.length]).toEqual([
      401,
      'SessionExpired',
      0
    ]);
    for (const other of ['alice', 'ana mar%C3%ADa ', 'ana%20mar%C3%ADa%20']) {
      expect((await api(request('/api/v1/x', {cookies, tabUser: other}), deps)).status).toBe(401);
    }
    expect(fetch).not.toHaveBeenCalled();

    const named = await api(request('/api/v1/x', {cookies, tabUser: encodeURIComponent('ana maría')}), deps);
    expect(named.status).toBe(200);
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).has('x-dq-user')).toBe(false);
  });

  it.each([
    '/api//evil.example/x',
    '/api/%2F%2Fevil.example/x',
    '/api/https:%2F%2Fevil.example/x',
    '/api/\\\\evil.example/x'
  ])('never reaches another host from %s', async (path) => {
    const deps = await signedIn();
    const fetch = vi.fn<(url: string) => Promise<Response>>(async () => json(200, {}));
    vi.stubGlobal('fetch', fetch);
    const response = await api(request(path, {cookies}), deps);
    const target = fetch.mock.calls[0]?.[0];
    expect(target === undefined ? response.status : new URL(target).origin).toBe(target === undefined ? 404 : API);
  });

  it('refreshes a token within 300 seconds of expiry before forwarding, and not one further off', async () => {
    for (const [expiresIn, refreshes] of [
      [299, 1],
      [301, 0]
    ]) {
      const deps = await signedIn(storedSession({tokenExpiresAt: NOW + expiresIn}).item);
      const fetch = vi.fn(async (url: string) =>
        url.endsWith('/oauth2/token') ? json(200, {id_token: idToken()}) : json(200, {})
      );
      vi.stubGlobal('fetch', fetch);
      await api(request('/api/v1/x', {cookies}), deps);
      expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/oauth2/token'))).toHaveLength(refreshes);
    }
  });

  it('refuses a body over 10 MB, declared or chunked, and forwards none of it', async () => {
    const deps = await signedIn();
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const declared = request('/api/v1/x', {
      method: 'POST',
      cookies,
      headers: {origin: PORTAL, 'content-length': String(10 * 1024 * 1024 + 1)}
    });
    expect((await api(declared, deps)).status).toBe(413);

    const big = new Uint8Array(10 * 1024 * 1024 + 1);
    const chunked = new Request(`${PORTAL}/api/v1/x`, {
      method: 'POST',
      headers: {origin: PORTAL, cookie: `${SESSION_COOKIE}=${cookies[SESSION_COOKIE]}`, 'x-dq-user': 'alice'},
      body: new ReadableStream({start: (c) => (c.enqueue(big), c.close())}),
      duplex: 'half'
    } as RequestInit);
    expect((await api(chunked, deps)).status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();

    const exact = new Uint8Array(10 * 1024 * 1024).fill(7);
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => json(200, {received: (init.body as Uint8Array).byteLength}))
    );
    const whole = await api(
      request('/api/v1/x', {
        method: 'POST',
        cookies,
        headers: {origin: PORTAL, 'content-length': String(exact.byteLength)},
        body: exact
      }),
      deps
    );
    expect(await whole.json()).toEqual({received: 10 * 1024 * 1024});
  });

  it('answers 503 for a redirect and a stalled API, and passes the API 401 through untouched', async () => {
    const deps = await signedIn();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    for (const status of [302, 307]) {
      const fetch = vi.fn(async () => new Response(null, {status, headers: {location: 'https://elsewhere'}}));
      vi.stubGlobal('fetch', fetch);
      expect((await api(request('/api/v1/x', {cookies}), deps)).status).toBe(503);
      expect(fetch).toHaveBeenCalledOnce();
    }

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(401, {error: {code: 'SessionExpired', requestId: 'g'}}, {'www-authenticate': 'Bearer'}))
    );
    const passed = await api(request('/api/v1/x', {cookies}), deps);
    expect(passed.status).toBe(401);
    expect(passed.headers.get('www-authenticate')).toBe('Bearer');
    expect(await passed.json()).toEqual({error: {code: 'SessionExpired', requestId: 'g'}});
    expect(deps.dynamo.table.size).toBe(1);

    vi.useFakeTimers();
    vi.setSystemTime(NOW * 1000);
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => init.signal?.addEventListener('abort', () => reject(init.signal?.reason)))
      )
    );
    const stalled = api(request('/api/v1/x', {cookies}), deps);
    await vi.advanceTimersByTimeAsync(35_000);
    expect((await stalled).status).toBe(503);
  });

  it('lets an answer that began within 35 seconds finish streaming after them', async () => {
    const deps = await signedIn();
    vi.useFakeTimers();
    vi.setSystemTime(NOW * 1000);
    const encode = (text: string) => new TextEncoder().encode(text);
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async (_url: string, init: RequestInit) =>
          new Response(
            new ReadableStream({
              start(controller) {
                init.signal?.addEventListener('abort', () => controller.error(init.signal?.reason));
                controller.enqueue(encode('{"ok":'));
                setTimeout(() => {
                  controller.enqueue(encode('true}'));
                  controller.close();
                }, 40_000);
              }
            }),
            {status: 200, headers: {'content-type': 'application/json'}}
          )
      )
    );

    const response = await api(request('/api/v1/x', {cookies}), deps);
    const body = response.text();
    await vi.advanceTimersByTimeAsync(40_000);

    expect(await body).toBe('{"ok":true}');
  });
});

describe('the configuration', () => {
  it('answers 503 naming nothing when a setting is unset, and every refusal is a contract code', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    for (const name of ['PORTAL_ORIGIN', 'OIDC_CLIENT_SECRET', 'SESSION_TABLE_NAME']) vi.stubEnv(name, '');

    const response = await route(session)(request('/auth/session'));

    expect(response.status).toBe(503);
    const body = await response.text();
    expect(body).toMatch(/^\{"error": \{"code": "ApiUnavailable", "requestId": "[^"]+"\}\}$/);
    expect(API_ERROR_CODES).toEqual(
      expect.arrayContaining(['SessionExpired', 'AccessDenied', 'NotFound', 'PayloadTooLarge', 'ApiUnavailable'])
    );
    expect(testConfig().clientSecret).not.toBe('');
  });
});
