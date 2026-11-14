import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {SESSION_COOKIE, SIGNIN_COOKIE, signinCookie} from './cookies';
import {api, callback, logout, refresh, session} from './handlers';
import {sessionKey} from './session';
import {NOW, PORTAL, idToken, json, testConfig, testDeps} from './testSupport';

/**
 * No credential reaches a log or a response body, on any failure exit.
 *
 * Every credential is a distinctive value here, and every exit the server can take on a fault is
 * driven, with the doubles echoing what they were sent the way a careless provider or a raised
 * error would. Then every console call and every response body is searched for each value.
 */

const mark = (name: string) => ['sentinel', name, '7c2e'].join('-');
const SECRET = mark('secret');
const REFRESH = mark('refresh');
const CODE = mark('code');
const VERIFIER = mark('verifier').padEnd(43, 'v');
const COOKIE = mark('cookie').padEnd(43, 'c');
const ID_TOKEN = idToken({jti: mark('idtoken')});
const SENTINELS = [SECRET, REFRESH, CODE, VERIFIER, COOKIE, sessionKey(COOKIE), ID_TOKEN, mark('idtoken')];

const logged: string[] = [];

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW * 1000);
  for (const method of ['error', 'warn', 'log', 'info', 'debug'] as const) {
    vi.spyOn(console, method).mockImplementation((...args: unknown[]) => void logged.push(args.map(String).join(' ')));
  }
});

afterEach(() => {
  logged.length = 0;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A double that fails and echoes everything it was sent, as the worst provider would. */
function echoingFailure(status: number, error: string) {
  return vi.fn(async (_url: string, init?: RequestInit) =>
    json(status, {error, error_description: `${String(init?.body)} ${new Headers(init?.headers).get('authorization')}`})
  );
}

it('keeps every credential out of every log line and every response body', async () => {
  const deps = testDeps(testConfig({clientSecret: SECRET}));
  const item = {
    pk: sessionKey(COOKIE),
    idToken: ID_TOKEN,
    refreshToken: REFRESH,
    tokenExpiresAt: NOW + 10,
    sessionExpiresAt: NOW + 86400,
    expiresAt: NOW + 86400,
    version: 0
  };
  const transaction = {state: 's'.repeat(43), codeVerifier: VERIFIER, nonce: 'n'.repeat(43)};
  const signin = signinCookie(transaction).split(';')[0].split('=')[1];
  const cookie = `${SESSION_COOKIE}=${COOKIE}; ${SIGNIN_COOKIE}=${signin}`;
  const req = (path: string, method = 'GET') =>
    new Request(`${PORTAL}${path}`, {method, headers: {cookie, origin: PORTAL}});
  const bodies: string[] = [];
  const run = async (response: Promise<Response>) => bodies.push(await (await response).text());

  vi.stubGlobal('fetch', echoingFailure(400, 'invalid_request'));
  await run(callback(req(`/auth/callback?code=${CODE}&state=${transaction.state}`), deps));

  await deps.store.put(item);
  for (const [status, error] of [
    [400, 'invalid_client'],
    [500, 'server_error']
  ] as const) {
    vi.stubGlobal('fetch', echoingFailure(status, error));
    await run(refresh(req('/auth/refresh', 'POST'), deps));
    await run(session(req('/auth/session'), deps));
  }

  vi.spyOn(deps.store, 'get').mockRejectedValueOnce(new Error(`store failed for ${COOKIE} ${REFRESH}`));
  await run(session(req('/auth/session'), deps));

  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Promise.reject(new Error(`API down ${ID_TOKEN}`)))
  );
  await deps.store.put({...item, tokenExpiresAt: NOW + 3600});
  await run(api(req('/api/v1/x'), deps));

  vi.stubGlobal('fetch', echoingFailure(400, 'unsupported_token_type'));
  await run(logout(req('/auth/logout', 'POST'), deps));

  vi.stubGlobal('fetch', echoingFailure(400, 'invalid_grant'));
  await deps.store.put(item);
  await run(refresh(req('/auth/refresh', 'POST'), deps));

  expect(bodies).toHaveLength(9);
  expect(logged.length).toBeGreaterThan(0);
  const everything = [...logged, ...bodies].join('\n');
  for (const sentinel of SENTINELS) expect(everything).not.toContain(sentinel);
});
