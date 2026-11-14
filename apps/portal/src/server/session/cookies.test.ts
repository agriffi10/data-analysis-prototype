import {describe, expect, it} from 'vitest';
import {SESSION_COOKIE, SIGNIN_COOKIE, readCookie} from './cookies';

/** A request carrying exactly this `Cookie` header. */
const carrying = (cookie: string) => new Request('https://portal.example.test/', {headers: {cookie}});

describe('reading a cookie', () => {
  it('reads a pair padded with spaces and tabs, and nothing whose name differs by any other byte', () => {
    for (const name of [SESSION_COOKIE, SIGNIN_COOKIE]) {
      expect(readCookie(carrying(`a=1;  \t${name}\t =value; b=2`), name)).toBe('value');

      // 0xA0 reaches Node as U+00A0, which String.prototype.trim strips; the browser gave this cookie
      // none of the __Host- prefix's protection, because its stored name starts with that byte.
      expect(readCookie(carrying(`\u00a0${name}=planted`), name)).toBeUndefined();
      expect(readCookie(carrying(`${name}\u00a0=planted`), name)).toBeUndefined();
      expect(readCookie(carrying(`\u00a0${name}=planted; ${name}=real`), name)).toBe('real');
    }
  });
});
