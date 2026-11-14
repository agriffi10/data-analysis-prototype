import 'server-only';
import {createHash} from 'node:crypto';
import type {SessionConfig} from './config';
import {claimsOf, randomToken, refreshTokens, revoke, userOf} from './oidc';
import type {IssuedTokens, LoadedSession, SessionItem, SessionStore} from './session.types';

/**
 * Refresh when the ID token expires within this many seconds: room for the API Gateway
 * integration's 30 seconds and for clock skew, with plenty to spare.
 */
export const REFRESH_MARGIN_SECONDS = 300;

/**
 * A backstop on the writes one refresh makes, not a limit a burst reaches: every write after the
 * first follows another refresh's write of a token issued in an earlier whole second than this one's,
 * so losing five times takes five concurrent refreshes from five distinct earlier seconds.
 */
export const REFRESH_WRITE_ATTEMPTS = 5;

/** A session id is 32 random bytes, base64url: 43 characters. Anything else is not one. */
const SESSION_ID = /^[A-Za-z0-9_-]{43}$/;

/** Whole seconds since the epoch. */
export const nowSeconds = (): number => Math.floor(Date.now() / 1000);

/**
 * The store key for a cookie's session id. A digest, so the table never holds a usable cookie.
 *
 * @param sessionId - The cookie's value.
 * @returns The key.
 */
export function sessionKey(sessionId: string): string {
  return `session#${createHash('sha256').update(sessionId).digest('hex')}`;
}

/**
 * Whether a cookie's value has the shape of a session id, checked before any store call.
 *
 * @param value - The cookie's value.
 * @returns True for a well-formed id.
 */
export function isSessionId(value: string | undefined): value is string {
  return value !== undefined && SESSION_ID.test(value);
}

/**
 * Store a new session for tokens a sign-in produced, under a fresh id.
 *
 * @param store - The session store.
 * @param config - The session configuration.
 * @param tokens - The sign-in's tokens, refresh token included.
 * @param now - The current time, epoch seconds.
 * @returns The new session's id, for the cookie.
 */
export async function createSession(
  store: SessionStore,
  config: SessionConfig,
  tokens: Required<IssuedTokens>,
  now: number = nowSeconds()
): Promise<string> {
  const sessionId = randomToken();
  const sessionExpiresAt = now + config.maxAgeSeconds;
  await store.put({
    pk: sessionKey(sessionId),
    idToken: tokens.idToken,
    refreshToken: tokens.refreshToken,
    tokenExpiresAt: tokens.tokenExpiresAt,
    sessionExpiresAt,
    expiresAt: sessionExpiresAt,
    version: 0
  });
  return sessionId;
}

/**
 * The active session an item describes.
 *
 * @param item - The stored item.
 * @param idToken - The ID token to forward, which may be newer than the item's.
 * @returns The session, or absent when the token names no user.
 */
function active(item: SessionItem, idToken: string): LoadedSession {
  const user = userOf(idToken);
  return user ? {status: 'active', pk: item.pk, idToken, user} : {status: 'absent'};
}

/**
 * Load the session a cookie names, refreshing its ID token first when it is near expiry or the
 * caller forces it.
 *
 * Expiry is checked here, on every read: DynamoDB deletes an expired item within days and returns it
 * until then, so the TTL is never the boundary. A fault answers `unavailable` and never `absent`:
 * only a missing or expired item, or a refresh token the provider refuses, ends a session.
 *
 * Two requests carrying one cookie, on one task or two, may refresh at once. Each refresh is a
 * compare-and-set on the version it read. The loser of a proactive refresh adopts the stored token,
 * which serves it as well as its own. The loser of a forced refresh adopts it only when it was issued
 * in the same second as its own or later, and otherwise writes its own against the version it re-read:
 * a forced refresh exists to pick up a membership granted a moment ago, and an older token may predate
 * the grant. So the stored token only ever moves forward, and a burst of forced refreshes settles on
 * one write.
 *
 * @param store - The session store.
 * @param config - The session configuration.
 * @param cookieValue - The session cookie's value, if any.
 * @param options - `forceRefresh` refreshes whatever the token's expiry.
 * @param now - The current time, epoch seconds.
 * @returns The session's state.
 */
export async function loadSession(
  store: SessionStore,
  config: SessionConfig,
  cookieValue: string | undefined,
  options: {forceRefresh: boolean},
  now: number = nowSeconds()
): Promise<LoadedSession> {
  if (!isSessionId(cookieValue)) return {status: 'absent'};
  const pk = sessionKey(cookieValue);

  let item: SessionItem | null;
  try {
    item = await store.get(pk);
  } catch {
    console.error('session: the store did not answer a read');
    return {status: 'unavailable'};
  }
  if (item === null) return {status: 'absent'};
  if (now >= item.sessionExpiresAt) {
    await store.delete(pk).catch(() => console.error('session: an expired session could not be deleted'));
    return {status: 'absent'};
  }
  if (!options.forceRefresh && item.tokenExpiresAt - now > REFRESH_MARGIN_SECONDS) return active(item, item.idToken);

  const refreshed = await refreshTokens(config, item.refreshToken, now);
  if (!refreshed.ok) {
    if (refreshed.failure === 'invalid_grant') {
      await store.delete(pk).catch(() => console.error('session: a refused session could not be deleted'));
      return {status: 'absent'};
    }
    console.error(`session: a refresh failed (${refreshed.failure})`);
    const stillValid = !options.forceRefresh && item.tokenExpiresAt > now;
    return stillValid ? active(item, item.idToken) : {status: 'unavailable'};
  }

  const next = {idToken: refreshed.tokens.idToken, tokenExpiresAt: refreshed.tokens.tokenExpiresAt};
  const issuedAt = issuedAtOf(next.idToken);
  let expectedVersion = item.version;
  try {
    for (let attempt = 0; attempt < REFRESH_WRITE_ATTEMPTS; attempt += 1) {
      if (await store.replaceTokens(pk, expectedVersion, next)) return active(item, next.idToken);
      const stored = await store.get(pk);
      if (stored === null) return {status: 'absent'};
      if (!options.forceRefresh || issuedAtOf(stored.idToken) >= issuedAt) return active(stored, stored.idToken);
      expectedVersion = stored.version;
    }
  } catch {
    console.error('session: the store did not answer a refresh write');
    return {status: 'unavailable'};
  }
  console.error('session: a refresh lost every write');
  return {status: 'unavailable'};
}

/**
 * When the provider issued an ID token, which orders two refreshes' tokens.
 *
 * @param idToken - The ID token.
 * @returns Its `iat`, epoch seconds, or 0 when it has none, so a token without one counts as oldest.
 */
function issuedAtOf(idToken: string): number {
  const iat = claimsOf(idToken)?.iat;
  return typeof iat === 'number' && Number.isFinite(iat) ? iat : 0;
}

/**
 * End the session a cookie names: delete it, then revoke its refresh token.
 *
 * The delete comes first, so the session is over even when the revocation fails; a failed
 * revocation is logged by its outcome and nothing else.
 *
 * @param store - The session store.
 * @param config - The session configuration.
 * @param cookieValue - The session cookie's value, if any.
 * @returns False when the store failed, so the session may still be live.
 */
export async function endSession(
  store: SessionStore,
  config: SessionConfig,
  cookieValue: string | undefined
): Promise<boolean> {
  if (!isSessionId(cookieValue)) return true;
  const pk = sessionKey(cookieValue);
  let item: SessionItem | null;
  try {
    item = await store.get(pk);
    if (item !== null) await store.delete(pk);
  } catch {
    console.error('session: the store did not answer a sign-out');
    return false;
  }
  if (item !== null && !(await revoke(config, item.refreshToken))) {
    console.error('session: the provider did not accept a revocation');
  }
  return true;
}
