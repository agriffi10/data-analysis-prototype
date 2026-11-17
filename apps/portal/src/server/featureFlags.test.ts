import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {headers} from 'next/headers';
import {
  GATE_MAX_AGE_MS,
  HELD_MAX_AGE_MS,
  REFRESH_DEADLINE_MS,
  heldFeatureFlags,
  resetServerFeatureFlagsForTests,
  serverFeatureFlags,
  serverRouteGate
} from './featureFlags';
import {FEATURE_FLAG_DEFAULTS} from '../features/feature-flags/featureFlagDefaults';
import {answer, envelope, flagDocument, settle, signedInRequest} from './featureFlagsTestSupport';
import {SessionConfigError} from './session/config';
import {SESSION_COOKIE} from './session/cookies';
import {environmentDeps} from './session/handlers';
import {NOW} from './session/testSupport';

vi.mock('next/headers', () => ({headers: vi.fn()}));
vi.mock('./session/handlers', () => ({environmentDeps: vi.fn()}));

const SECOND = 1000;
const MINUTE = 60 * SECOND;

/** The API, stubbed: each call answers with the next of `answers`, the last repeating. */
function api(...answers: ((init: RequestInit) => Promise<Response>)[]) {
  const fetch = vi.fn(async (_target: string, init: RequestInit) =>
    (answers.length > 1 ? answers.shift()! : answers[0])(init)
  );
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

const flagsOff = {...FEATURE_FLAG_DEFAULTS, query: false};
const answersFlagsOff = () => Promise.resolve(envelope(flagDocument({query: false})));

/** Hold `query: false` as a set the API answered now, through the real refresh. */
async function holdNow() {
  api(answersFlagsOff);
  await serverFeatureFlags();
  await settle();
}

beforeEach(() => {
  vi.useFakeTimers({now: NOW * SECOND});
  resetServerFeatureFlagsForTests();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.mocked(headers).mockReset();
  vi.mocked(environmentDeps).mockReset();
});

describe('a request the server sends no flags', () => {
  it('carries no session cookie, so the store is never read', async () => {
    const {deps} = await signedInRequest();
    vi.mocked(headers).mockResolvedValue(new Headers() as never);
    const get = vi.spyOn(deps.store, 'get');
    const fetch = api(answersFlagsOff);

    expect(await serverFeatureFlags()).toBeUndefined();
    expect(get).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('carries the cookie under a name padded with U+00A0, which is not the session cookie', async () => {
    const {deps, cookie} = await signedInRequest();
    vi.mocked(headers).mockResolvedValue(new Headers({cookie: `\u00a0${SESSION_COOKIE}=${cookie}`}) as never);
    const get = vi.spyOn(deps.store, 'get');

    expect(await serverFeatureFlags()).toBeUndefined();
    expect(get).not.toHaveBeenCalled();
  });

  it.each([
    ['a session the store does not hold', async () => (await signedInRequest()).deps.dynamo.table.clear()],
    ['an expired session', async () => void (await signedInRequest({sessionExpiresAt: NOW, expiresAt: NOW}))],
    [
      'a store that throws',
      async () => {
        const {deps} = await signedInRequest();
        vi.spyOn(deps.store, 'get').mockRejectedValue(new Error('timed out'));
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
      }
    ]
  ])('names %s, and makes no API request', async (_case, arrange) => {
    await arrange();
    const fetch = api(answersFlagsOff);

    expect(await serverFeatureFlags()).toBeUndefined();
    await settle();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('runs on an incomplete session configuration, after one log line', async () => {
    await signedInRequest();
    vi.mocked(environmentDeps).mockImplementation(() => {
      throw new SessionConfigError('API_ORIGIN');
    });
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    await expect(serverFeatureFlags()).resolves.toBeUndefined();
    expect(error).toHaveBeenCalledTimes(1);
    expect(error.mock.calls[0][0]).toContain('SessionConfigError');
  });
});

describe('a signed-in request with no held set', () => {
  it('answers nothing, starts one request with the session’s token, and is answered by the next call', async () => {
    const {item} = await signedInRequest();
    const fetch = api(answersFlagsOff);

    expect(await serverFeatureFlags()).toBeUndefined();
    await settle();

    expect(fetch).toHaveBeenCalledTimes(1);
    const [target, init] = fetch.mock.calls[0];
    expect(target).toBe('https://api.example.test/v1/feature-flags');
    expect(init).toMatchObject({
      cache: 'no-store',
      redirect: 'manual',
      headers: {authorization: `Bearer ${item.idToken}`}
    });
    expect(await serverFeatureFlags()).toEqual({flags: flagsOff, readAt: NOW * SECOND});
  });

  it('starts no request on a token with 30 seconds left', async () => {
    await signedInRequest({tokenExpiresAt: NOW + 30});
    const fetch = api(answersFlagsOff);

    await serverFeatureFlags();
    await settle();

    expect(fetch).not.toHaveBeenCalled();
  });

  it('starts one request for ten concurrent calls', async () => {
    await signedInRequest();
    const fetch = api(answersFlagsOff);

    await Promise.all(Array.from({length: 10}, () => serverFeatureFlags()));
    await settle();

    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('settles without waiting on an API that never answers', async () => {
    await signedInRequest();
    api(() => new Promise<Response>(() => undefined));

    await expect(serverFeatureFlags()).resolves.toBeUndefined();
  });
});

describe('a held set, by its age', () => {
  it.each([
    ['30 seconds', true, 0, 30 * SECOND],
    ['5 minutes', true, 1, 5 * MINUTE],
    ['61 minutes', false, 1, 61 * MINUTE]
  ])('a set %s old is answered: %s, and starts %i request(s)', async (_age, answered, requests, age) => {
    await signedInRequest({tokenExpiresAt: NOW + 7200});
    await holdNow();
    vi.setSystemTime(NOW * SECOND + age);
    const fetch = api(answersFlagsOff);

    const sent = await serverFeatureFlags();
    await settle();

    expect(sent).toEqual(answered ? {flags: flagsOff, readAt: NOW * SECOND} : undefined);
    expect(fetch).toHaveBeenCalledTimes(requests);
  });

  it('is exactly the set and when the API answered it, with nothing of the session in it', async () => {
    const {item} = await signedInRequest();
    await holdNow();

    const sent = await serverFeatureFlags();

    expect(sent).toEqual({flags: flagsOff, readAt: NOW * SECOND});
    expect(JSON.stringify(sent)).not.toContain(item.idToken);
  });
});

describe('a refresh that fails', () => {
  const document = flagDocument({query: false});
  const failures: [string, string, (init: RequestInit) => Promise<Response>, number][] = [
    ['a 500', 'status 500', async () => answer(500, {}), 0],
    ['a 404', 'status 404', async () => answer(404, {}), 0],
    ['a 302', 'redirect', async () => answer(302, {}), 0],
    ['an answer {}', 'envelope', async () => answer(200, {}), 0],
    ['a body with version 2', 'document FeatureFlagsUnusable', async () => envelope({...document, version: 2}), 0],
    [
      'a timeout',
      'no answer',
      // Answers nothing until the deadline aborts it, as fetch does.
      ({signal}) =>
        new Promise<Response>((_resolve, reject) => {
          signal!.addEventListener('abort', () => reject(signal!.reason));
        }),
      REFRESH_DEADLINE_MS
    ]
  ];

  it.each(failures)(
    'keeps the held set after %s, logs one line naming %s, and pauses a minute from the failure',
    async (_case, reason, failing, failsAfter) => {
      const {item} = await signedInRequest({tokenExpiresAt: NOW + 7200});
      await holdNow();
      const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      vi.setSystemTime(NOW * SECOND + 5 * MINUTE);
      const fetch = api(failing, answersFlagsOff);

      await serverFeatureFlags();
      await vi.advanceTimersByTimeAsync(failsAfter);
      await settle();
      const failedAt = Date.now();

      expect(fetch).toHaveBeenCalledTimes(1);
      expect(heldFeatureFlags()).toEqual({flags: flagsOff, readAt: NOW * SECOND});
      expect(error).toHaveBeenCalledTimes(1);
      const [line] = error.mock.calls[0] as [string];
      expect(line).toContain(`(${reason})`);
      expect(line).not.toContain(item.idToken);
      expect(line).not.toContain(JSON.stringify(document));

      vi.setSystemTime(failedAt + 59 * SECOND);
      await serverFeatureFlags();
      await settle();
      expect(fetch).toHaveBeenCalledTimes(1);

      vi.setSystemTime(failedAt + 61 * SECOND);
      await serverFeatureFlags();
      await settle();
      expect(fetch).toHaveBeenCalledTimes(2);
    }
  );
});

describe('the held set, for the area layouts', () => {
  it('is answered at 30 minutes and not at 61, with no request and no store read either way', async () => {
    const {deps} = await signedInRequest();
    await holdNow();
    const get = vi.spyOn(deps.store, 'get');
    const fetch = api(answersFlagsOff);

    vi.setSystemTime(NOW * SECOND + 30 * MINUTE);
    expect(heldFeatureFlags()).toEqual({flags: flagsOff, readAt: NOW * SECOND});
    vi.setSystemTime(NOW * SECOND + HELD_MAX_AGE_MS + MINUTE);
    expect(heldFeatureFlags()).toBeUndefined();

    await settle();
    expect(fetch).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });
});

describe('an area gate on an ageing set', () => {
  it('answers from a set inside its window and leaves an older one to the browser', async () => {
    await signedInRequest();
    await holdNow();

    vi.setSystemTime(NOW * SECOND + GATE_MAX_AGE_MS - SECOND);
    expect(serverRouteGate('/query')).toEqual({kind: 'unavailable', flag: 'query', fallback: 'files'});
    vi.setSystemTime(NOW * SECOND + GATE_MAX_AGE_MS);
    expect(serverRouteGate('/query')).toEqual({kind: 'open'});
    expect(heldFeatureFlags()?.flags.query).toBe(false);
  });
});
