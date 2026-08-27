// The browser's half of the auth boundary.
//
// EVERY ASSERTION THAT MATTERS HERE IS A FETCH COUNT. A refresh loop against a dead
// refresh token is invisible in a passing test that only checks the returned value —
// the call still resolves to "sign in again", correctly, after hammering the API — and
// obvious in production. So the counts are what is asserted, not just the outcomes.

import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiFetch} from './apiClient';
import {toUserMessage} from './errorMessages';

const getIdToken = vi.hoisted(() => vi.fn());
const configValue = vi.hoisted(() => vi.fn());

vi.mock('./awsCredentials', () => ({getIdToken}));
vi.mock('./runtimeConfig', () => ({configValue}));

/** A fetch stub that answers with the given statuses in order, counting calls. */
function respondWith(...statuses: number[]) {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string) => {
    calls.push(url);
    const status = statuses[calls.length - 1] ?? statuses[statuses.length - 1];
    return {
      status,
      ok: status >= 200 && status < 300,
      json: async () => ({username: 'alice'})
    } as unknown as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return {fetchMock, calls};
}

beforeEach(() => {
  vi.clearAllMocks();
  configValue.mockReturnValue('https://api.example');
  getIdToken.mockResolvedValue({success: true, data: 'a-token'});
});

describe('apiFetch', () => {
  it('attaches the token as a bearer and returns the parsed body', async () => {
    const {fetchMock} = respondWith(200);

    const result = await apiFetch<{username: string}>({path: '/_auth/whoami'});

    expect(result).toEqual({success: true, data: {username: 'alice'}});
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example/_auth/whoami',
      expect.objectContaining({headers: {authorization: 'Bearer a-token'}})
    );
  });

  it('reads the token per call rather than caching it', async () => {
    respondWith(200);

    await apiFetch({path: '/one'});
    await apiFetch({path: '/two'});

    // Amplify owns the token's lifecycle including the silent refresh. A cache here
    // serves a stale token after one, and the staleness is invisible until it expires.
    expect(getIdToken).toHaveBeenCalledTimes(2);
  });

  it('never forces a refresh on the first attempt', async () => {
    respondWith(200);
    await apiFetch({path: '/one'});
    expect(getIdToken).toHaveBeenCalledWith(false);
  });

  it('issues NO request at all when the token cannot be obtained', async () => {
    const {fetchMock} = respondWith(200);
    getIdToken.mockResolvedValue({success: false, error: {message: 'no session'}});

    const result = await apiFetch({path: '/_auth/whoami'});

    expect(fetchMock).toHaveBeenCalledTimes(0);
    expect(result).toEqual({success: false, error: {message: '', code: 'SessionExpired'}});
  });

  it('refreshes once and retries once on a 401, then succeeds', async () => {
    const {fetchMock} = respondWith(401, 200);

    const result = await apiFetch<{username: string}>({path: '/_auth/whoami'});

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getIdToken).toHaveBeenNthCalledWith(1, false);
    expect(getIdToken).toHaveBeenNthCalledWith(2, true);
  });

  it('does NOT retry a second time when the retry also 401s', async () => {
    const {fetchMock} = respondWith(401, 401);

    const result = await apiFetch({path: '/_auth/whoami'});

    // The count is the assertion. Without the bound this loops against a dead refresh
    // token, which the returned value below cannot distinguish.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getIdToken).toHaveBeenCalledTimes(2);
    expect(result).toEqual({success: false, error: {message: '', code: 'SessionExpired'}});
  });

  it.each([
    ['429', 429],
    ['503', 503],
    ['500', 500],
    ['404', 404]
  ])('does not retry a %s', async (_label, status) => {
    const {fetchMock} = respondWith(status);

    await apiFetch({path: '/_auth/whoami'});

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not retry a network failure', async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await apiFetch({path: '/_auth/whoami'});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result).toEqual({success: false, error: {message: '', code: 'ApiUnavailable'}});
  });

  it('maps a 403 to a DIFFERENT user message than a 401', async () => {
    respondWith(403);
    const denied = await apiFetch({path: '/_auth/whoami'});

    respondWith(401, 401);
    const expired = await apiFetch({path: '/_auth/whoami'});

    expect(denied).toEqual({success: false, error: {message: '', code: 'AccessDenied'}});
    expect(expired).toEqual({success: false, error: {message: '', code: 'SessionExpired'}});

    // The difference between "sign in again" and "signing in again cannot help". One
    // wording for both is the defect this asserts against, and it is a wording defect
    // rather than a logic one — which is why it is checked through the mapper.
    const deniedText = toUserMessage(denied.success ? undefined : denied.error).message;
    const expiredText = toUserMessage(expired.success ? undefined : expired.error).message;
    expect(deniedText).not.toEqual(expiredText);
    expect(expiredText.toLowerCase()).toContain('sign in');
  });

  it('never throws, and never renders API or provider text', async () => {
    respondWith(500);
    const result = await apiFetch({path: '/_auth/whoami'});

    expect(result.success).toBe(false);
    if (!result.success) {
      // The code carries the wording; the message is not a place for server text.
      expect(result.error.message).toBe('');
      const rendered = toUserMessage(result.error).message;
      expect(rendered).not.toContain('500');
    }
  });

  it('fails with no request when the API origin is not configured', async () => {
    const {fetchMock} = respondWith(200);
    configValue.mockReturnValue(undefined);

    const result = await apiFetch({path: '/_auth/whoami'});

    expect(fetchMock).toHaveBeenCalledTimes(0);
    expect(result).toEqual({success: false, error: {message: '', code: 'ApiUnavailable'}});
  });

  it('fails with no request when reading the configuration THROWS', async () => {
    // A production build throws here before the runtime document has loaded. `apiFetch`
    // promises never to throw and this is the first thing it does, so the throw has to
    // be caught rather than assumed away.
    const {fetchMock} = respondWith(200);
    configValue.mockImplementation(() => {
      throw new Error('Runtime configuration read before /config.json was loaded');
    });

    const result = await apiFetch({path: '/_auth/whoami'});

    expect(fetchMock).toHaveBeenCalledTimes(0);
    expect(result).toEqual({success: false, error: {message: '', code: 'ApiUnavailable'}});
  });

  it('does not read the 401 body, because the API does not disclose a cause', async () => {
    const json = vi.fn(async () => ({code: 'TokenExpired'}));
    const fetchMock = vi.fn(async () => ({status: 401, ok: false, json}) as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await apiFetch({path: '/_auth/whoami'});

    // Every 401 body is byte-identical on purpose. A client that read one would be
    // relying on a discriminator the API deliberately does not provide.
    expect(json).not.toHaveBeenCalled();
  });
});
