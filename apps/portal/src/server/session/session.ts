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
 * @param config - The session configuration, for the username claim.
 * @param item - The stored item.
 * @param idToken - The ID token to forward, which may be newer than the item's.
 * @returns The session, or absent when the token names no user.
 */
function active(config: SessionConfig, item: SessionItem, idToken: string): LoadedSession {
  const user = userOf(config, idToken);
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
  if (item === null || !createdHere(item, config)) return {status: 'absent'};
  if (now >= item.sessionExpiresAt) {
    await store.delete(pk).catch(() => console.error('session: an expired session could not be deleted'));
    return {status: 'absent'};
  }
  if (!options.forceRefresh && item.tokenExpiresAt - now > REFRESH_MARGIN_SECONDS)
    return active(config, item, item.idToken);

  const refreshed = await refreshTokens(config, item.refreshToken, now);
  if (!refreshed.ok) {
    if (refreshed.failure === 'invalid_grant') {
      await store.delete(pk).catch(() => console.error('session: a refused session could not be deleted'));
      return {status: 'absent'};
    }
    console.error(`session: a refresh failed (${refreshed.failure})`);
    const stillValid = !options.forceRefresh && item.tokenExpiresAt > now;
    return stillValid ? active(config, item, item.idToken) : {status: 'unavailable'};
  }

  const next = {idToken: refreshed.tokens.idToken, tokenExpiresAt: refreshed.tokens.tokenExpiresAt};
  const issuedAt = issuedAtOf(next.idToken);
  let expectedVersion = item.version;
  try {
    for (let attempt = 0; attempt < REFRESH_WRITE_ATTEMPTS; attempt += 1) {
      if (await store.replaceTokens(pk, expectedVersion, next)) return active(config, item, next.idToken);
      const stored = await store.get(pk);
      if (stored === null) return {status: 'absent'};
      if (!options.forceRefresh || issuedAtOf(stored.idToken) >= issuedAt)
        return active(config, stored, stored.idToken);
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
 * Read the session a cookie names without changing anything: one store read, the same checks
 * `loadSession` makes before it would refresh, and no refresh, no delete and no write.
 *
 * For a caller that only needs a token it can use now, such as the root layout reading the feature
 * flags once per document load: a refresh there would put a provider call on every page's critical
 * path. Because it never refreshes, a stored token that has expired, or that names no user, answers
 * `none`, which is also how a user the provider has revoked stops being served without a provider
 * call. A store fault answers `none` after one log line; this caller has no 503 to give.
 *
 * @param store - The session store.
 * @param config - The session configuration.
 * @param cookieValue - The session cookie's value, if any.
 * @param now - The current time, epoch seconds.
 * @returns The stored ID token and its expiry, or `none`.
 */
export async function peekSession(
  store: SessionStore,
  config: SessionConfig,
  cookieValue: string | undefined,
  now: number = nowSeconds()
): Promise<{status: 'active'; idToken: string; tokenExpiresAt: number} | {status: 'none'}> {
  if (!isSessionId(cookieValue)) return {status: 'none'};
  let item: SessionItem | null;
  try {
    item = await store.get(sessionKey(cookieValue));
  } catch {
    console.error('session: the store did not answer a peek');
    return {status: 'none'};
  }
  if (item === null || !createdHere(item, config)) return {status: 'none'};
  if (now >= item.sessionExpiresAt || now >= item.tokenExpiresAt) return {status: 'none'};
  if (!userOf(config, item.idToken)) return {status: 'none'};
  return {status: 'active', idToken: item.idToken, tokenExpiresAt: item.tokenExpiresAt};
}

/**
 * Whether a stored session was signed in through this server's own client.
 *
 * A dev server and the deployed portal share the session table, and the dev server's cookie is neither
 * prefixed nor `Secure`, so a dev cookie could reach any localhost server and be replayed against the
 * portal. A session another client created is treated as absent and left alone: refreshing it would send
 * its refresh token with the wrong secret, Cognito would refuse it, and the refusal would delete it.
 *
 * @param item - The stored session.
 * @param config - The session configuration.
 * @returns True when the stored ID token's `aud` is this server's client id.
 */
function createdHere(item: SessionItem, config: SessionConfig): boolean {
  return claimsOf(item.idToken)?.aud === config.clientId;
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
 * Delete the session a cookie names when a new sign-in replaces it, if this server created it.
 *
 * Its refresh token is not revoked: the sign-in that replaces it may be the same user's, in which case
 * revoking would gain nothing. A session another client created is left alone, as a load and a sign-out
 * leave it, so a replayed dev cookie cannot end the dev session through a production sign-in.
 *
 * @param store - The session store.
 * @param config - The session configuration.
 * @param cookieValue - The replaced session cookie's value, if any.
 * @returns Nothing.
 * @throws When the store does not answer; the caller logs it and carries on.
 */
export async function discardSession(
  store: SessionStore,
  config: SessionConfig,
  cookieValue: string | undefined
): Promise<void> {
  if (!isSessionId(cookieValue)) return;
  const pk = sessionKey(cookieValue);
  const item = await store.get(pk);
  if (item !== null && createdHere(item, config)) await store.delete(pk);
}

/**
 * End the session a cookie names: delete it, then revoke its refresh token.
 *
 * The delete comes first, so the session is over even when the revocation fails; a failed
 * revocation is logged by its outcome and nothing else. A session another client created is not this
 * server's to end, so it is left in place, as a session load leaves it.
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
    if (item !== null && !createdHere(item, config)) return true;
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
