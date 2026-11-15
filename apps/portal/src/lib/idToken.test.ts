import {afterEach, describe, expect, it, vi} from 'vitest';
import {getIdToken} from './idToken';

afterEach(() => vi.unstubAllGlobals());

/** A fetch double answering every request with this status. */
function answering(status: number) {
  const fetch = vi.fn(async () => new Response(null, {status}));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

describe('getIdToken', () => {
  it('posts /auth/refresh with no body when forced, and succeeds on 204', async () => {
    const fetch = answering(204);

    expect(await getIdToken(true)).toEqual({success: true, data: undefined});

    expect(fetch).toHaveBeenCalledExactlyOnceWith('/auth/refresh', {method: 'POST', credentials: 'same-origin'});
  });

  it('fails with the session code when the server answers 401', async () => {
    answering(401);

    expect(await getIdToken(true)).toEqual({success: false, error: {message: '', code: 'SessionExpired'}});
  });

  it('makes no request when not forced, because the server keeps the token fresh itself', async () => {
    const fetch = answering(204);

    expect(await getIdToken()).toEqual({success: true, data: undefined});

    expect(fetch).not.toHaveBeenCalled();
  });
});
