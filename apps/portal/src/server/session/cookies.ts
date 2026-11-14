import 'server-only';
import type {SignInTransaction} from './session.types';

/** The session cookie: an opaque id, for the life of the browser session. */
export const SESSION_COOKIE = '__Host-dq_session';

/** The sign-in transaction, from `/auth/login` to `/auth/callback`. */
export const SIGNIN_COOKIE = '__Host-dq_signin';

/**
 * An hour, because a sign-up or a password reset in Managed Login waits on an emailed code, and a
 * transaction that expired meanwhile would land a newly confirmed user on the failure page.
 */
export const SIGNIN_MAX_AGE_SECONDS = 3600;

/**
 * The attributes both cookies share. `__Host-` requires `Secure` and `Path=/` and forbids `Domain`,
 * which is what stops a sibling subdomain or the network planting either cookie.
 */
const ATTRIBUTES = 'Path=/; Secure; HttpOnly; SameSite=Lax';

/**
 * The session cookie's `Set-Cookie` value. No `Max-Age`: one sign-in covers the browser session, and
 * the server's own clocks bound it.
 *
 * @param sessionId - The opaque id.
 * @returns The header value.
 */
export function sessionCookie(sessionId: string): string {
  return `${SESSION_COOKIE}=${sessionId}; ${ATTRIBUTES}`;
}

/**
 * The sign-in cookie's `Set-Cookie` value, carrying the transaction as base64url JSON.
 *
 * @param transaction - The state, PKCE verifier and nonce.
 * @returns The header value.
 */
export function signinCookie(transaction: SignInTransaction): string {
  const value = Buffer.from(JSON.stringify(transaction)).toString('base64url');
  return `${SIGNIN_COOKIE}=${value}; ${ATTRIBUTES}; Max-Age=${SIGNIN_MAX_AGE_SECONDS}`;
}

/**
 * A `Set-Cookie` value that removes a cookie. The prefix's attributes must be repeated, or the
 * browser refuses the removal as it would refuse the cookie.
 *
 * @param name - The cookie.
 * @returns The header value.
 */
export function clearedCookie(name: typeof SESSION_COOKIE | typeof SIGNIN_COOKIE): string {
  return `${name}=; ${ATTRIBUTES}; Max-Age=0`;
}

/** The whitespace a `Cookie` header may carry around a pair: space and tab, and nothing else. */
const COOKIE_PADDING = /^[ \t]+|[ \t]+$/g;

/**
 * Read one cookie from a request.
 *
 * Only space and tab are trimmed. `String.prototype.trim` also strips U+00A0, which Node reads from a
 * 0xA0 header byte, so a cookie named 0xA0 followed by `__Host-dq_session` would read as the real one
 * while the browser, checking the prefix against the name it stored, gave it none of the prefix's
 * protection: any sibling subdomain could set it.
 *
 * @param request - The request.
 * @param name - The cookie's name, matched exactly.
 * @returns Its value, or undefined when absent.
 */
export function readCookie(request: Request, name: string): string | undefined {
  for (const part of (request.headers.get('cookie') ?? '').split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).replace(COOKIE_PADDING, '') === name) {
      return part.slice(at + 1).replace(COOKIE_PADDING, '');
    }
  }
  return undefined;
}

/**
 * Parse the sign-in cookie, refusing anything that is not exactly a transaction.
 *
 * @param value - The cookie's value.
 * @returns The transaction, or undefined.
 */
export function parseSignin(value: string | undefined): SignInTransaction | undefined {
  if (!value) return undefined;
  try {
    const parsed: unknown = JSON.parse(Buffer.from(value, 'base64url').toString('utf8'));
    if (typeof parsed !== 'object' || parsed === null) return undefined;
    const {state, codeVerifier, nonce} = parsed as Record<string, unknown>;
    if (typeof state !== 'string' || typeof codeVerifier !== 'string' || typeof nonce !== 'string') return undefined;
    return {state, codeVerifier, nonce};
  } catch {
    return undefined;
  }
}
