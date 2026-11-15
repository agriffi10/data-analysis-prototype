import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {getCurrentAuthUser, startSignIn, startSignOut, startSignUp} from './auth.service';
import {assignDocument} from '../../lib/documentNavigation';
import {setReturnPathIfAbsent} from '../../lib/returnPath';

vi.mock('../../lib/documentNavigation', () => ({assignDocument: vi.fn(), reloadDocument: vi.fn()}));
vi.mock('../../lib/returnPath', () => ({setReturnPathIfAbsent: vi.fn()}));

/** A fetch double answering each request with the next of these, in order. */
function answering(...answers: (Response | Error)[]) {
  const fetch = vi.fn(async () => {
    const next = answers.shift();
    if (next instanceof Error) throw next;
    return next ?? new Response(null, {status: 500});
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), {status});
const unavailable = {success: false, error: {message: '', code: 'ApiUnavailable'}};

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe('getCurrentAuthUser', () => {
  it('reads the user from /auth/session, and a 401 as signed out with the session code', async () => {
    const fetch = answering(json(200, {username: 'alice', email: 'alice@example.test'}), json(401, {}));

    expect(await getCurrentAuthUser()).toEqual({success: true, data: {username: 'alice', email: 'alice@example.test'}});
    expect(await getCurrentAuthUser()).toEqual({success: false, error: {message: '', code: 'SessionExpired'}});

    expect(fetch).toHaveBeenCalledWith('/auth/session', {credentials: 'same-origin', cache: 'no-store'});
  });

  it('answers ApiUnavailable for a 503, a network failure and a body that names no user', async () => {
    answering(json(503, {}), new TypeError('offline'), json(200, {username: ''}));

    for (let call = 0; call < 3; call += 1) expect(await getCurrentAuthUser()).toEqual(unavailable);
  });
});

describe('starting a sign-in or a sign-up', () => {
  it('records the default landing without replacing a recorded one, then moves to /auth/login', async () => {
    for (const start of [startSignIn, startSignUp]) {
      vi.clearAllMocks();

      expect(await start()).toEqual({success: true, data: undefined});

      expect(setReturnPathIfAbsent).toHaveBeenCalledExactlyOnceWith('/files');
      expect(assignDocument).toHaveBeenCalledExactlyOnceWith('/auth/login');
    }
  });
});

describe('startSignOut', () => {
  it('posts /auth/logout and moves to the logout page the server answers', async () => {
    const logoutUrl = 'https://auth.example.test/logout?client_id=c&logout_uri=https%3A%2F%2Fportal.example.test';
    const fetch = answering(json(200, {logoutUrl}));

    expect(await startSignOut()).toEqual({success: true, data: undefined});

    expect(fetch).toHaveBeenCalledExactlyOnceWith('/auth/logout', {method: 'POST', credentials: 'same-origin'});
    expect(assignDocument).toHaveBeenCalledExactlyOnceWith(logoutUrl);
  });

  it('moves nowhere on a 503, a network failure or a logout page that is not HTTPS', async () => {
    answering(json(503, {}), new TypeError('offline'), json(200, {logoutUrl: 'javascript:alert(1)'}));

    for (let call = 0; call < 3; call += 1) expect(await startSignOut()).toEqual(unavailable);

    expect(assignDocument).not.toHaveBeenCalled();
  });
});
