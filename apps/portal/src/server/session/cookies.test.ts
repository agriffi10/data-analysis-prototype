import {afterEach, describe, expect, it, vi} from 'vitest';
import {SESSION_COOKIE, SIGNIN_COOKIE, readCookie, readCookieHeader} from './cookies';

/** A request carrying exactly this `Cookie` header. */
const carrying = (cookie: string) => new Request('https://portal.example.test/', {headers: {cookie}});

describe.each([
  ['from a request', (cookie: string, name: string) => readCookie(carrying(cookie), name)],
  ['from a header string', (cookie: string, name: string) => readCookieHeader(cookie, name)]
])('reading a cookie %s', (_how, read) => {
  it('reads a pair padded with spaces and tabs, and nothing whose name differs by any other byte', () => {
    for (const name of [SESSION_COOKIE, SIGNIN_COOKIE]) {
      expect(read(`a=1;  \t${name}\t =value; b=2`, name)).toBe('value');

      // 0xA0 reaches Node as U+00A0, which String.prototype.trim strips; the browser gave this cookie
      // none of the __Host- prefix's protection, because its stored name starts with that byte.
      expect(read(`\u00a0${name}=planted`, name)).toBeUndefined();
      expect(read(`${name}\u00a0=planted`, name)).toBeUndefined();
      expect(read(`\u00a0${name}=planted; ${name}=real`, name)).toBe('real');
    }
  });
});

it('reads no cookie from a request that carried no header', () => {
  expect(readCookieHeader(null, SESSION_COOKIE)).toBeUndefined();
});

describe('the cookie names and attributes, by build', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  /** The cookie module as a server built with this `NODE_ENV` loads it. */
  const loadedUnder = async (nodeEnv: string) => {
    vi.stubEnv('NODE_ENV', nodeEnv);
    vi.resetModules();
    return import('./cookies');
  };

  it('names both cookies with the __Host- prefix and sets Secure in a built server', async () => {
    const cookies = await loadedUnder('production');

    expect([cookies.SESSION_COOKIE, cookies.SIGNIN_COOKIE]).toEqual(['__Host-dq_session', '__Host-dq_signin']);
    expect(cookies.sessionCookie('id')).toBe('__Host-dq_session=id; Path=/; Secure; HttpOnly; SameSite=Lax');
    expect(cookies.clearedCookie(cookies.SIGNIN_COOKIE)).toContain('; Secure;');
  });

  it('names both cookies without the prefix and without Secure under next dev', async () => {
    const cookies = await loadedUnder('development');

    expect([cookies.SESSION_COOKIE, cookies.SIGNIN_COOKIE]).toEqual(['dq_session', 'dq_signin']);
    expect(cookies.sessionCookie('id')).toBe('dq_session=id; Path=/; HttpOnly; SameSite=Lax');
    expect(cookies.clearedCookie(cookies.SESSION_COOKIE)).not.toContain('Secure');
  });
});
