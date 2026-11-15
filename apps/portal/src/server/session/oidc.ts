import 'server-only';
import {createHash, randomBytes} from 'node:crypto';
import type {SessionConfig} from './config';
import type {IssuedTokens, SessionUser, SignInTransaction} from './session.types';
import {deadline} from './deadline';

/** Every call to the token and revocation endpoints is bounded, so a stall answers 503. */
export const TOKEN_ENDPOINT_TIMEOUT_MS = 5_000;

/** Why a call to the token endpoint did not produce tokens. Only `invalid_grant` ends a session. */
export type TokenFailure = 'invalid_grant' | 'invalid_client' | 'rejected' | 'unavailable';

/** The outcome of a token-endpoint call. */
export type TokenResult = {ok: true; tokens: IssuedTokens} | {ok: false; failure: TokenFailure};

/**
 * Thirty-two random bytes, base64url: the session id, the state, the PKCE verifier and the nonce.
 *
 * @returns The value.
 */
export function randomToken(): string {
  return randomBytes(32).toString('base64url');
}

/**
 * A fresh sign-in transaction.
 *
 * @returns The state, PKCE verifier and nonce.
 */
export function newTransaction(): SignInTransaction {
  return {state: randomToken(), codeVerifier: randomToken(), nonce: randomToken()};
}

/**
 * The PKCE S256 challenge for a verifier.
 *
 * @param verifier - The code verifier.
 * @returns The challenge.
 */
export function codeChallenge(verifier: string): string {
  return createHash('sha256').update(verifier).digest('base64url');
}

/**
 * The callback the provider redirects to, built from configuration and never from the request.
 *
 * @param config - The session configuration.
 * @returns The redirect URI.
 */
export function redirectUri(config: SessionConfig): string {
  return `${config.portalOrigin}/auth/callback`;
}

/**
 * The provider's authorize URL for one transaction.
 *
 * @param config - The session configuration.
 * @param transaction - The state, verifier and nonce.
 * @returns The URL to redirect the browser to.
 */
export function authorizeUrl(config: SessionConfig, transaction: SignInTransaction): string {
  const url = new URL(config.authorizeUrl);
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: redirectUri(config),
    scope: 'openid email profile',
    state: transaction.state,
    nonce: transaction.nonce,
    code_challenge: codeChallenge(transaction.codeVerifier),
    code_challenge_method: 'S256'
  });
  if (config.identityProvider !== undefined) params.set('identity_provider', config.identityProvider);
  url.search = params.toString();
  return url.toString();
}

/**
 * `client_secret_basic`: the id and secret, each form-encoded, then base64.
 *
 * @param config - The session configuration.
 * @returns The Authorization header value.
 */
function basicAuthorization(config: SessionConfig): string {
  const pair = `${encodeURIComponent(config.clientId)}:${encodeURIComponent(config.clientSecret)}`;
  return `Basic ${Buffer.from(pair).toString('base64')}`;
}

/**
 * A JWT's payload, decoded without verifying it.
 *
 * The tokens this module reads come straight from the token endpoint over TLS, which OIDC Core
 * (§3.1.3.7, item 6) accepts in place of checking the signature; the API verifies the signature
 * on every forwarded call.
 *
 * @param jwt - The token.
 * @returns Its claims, or undefined when it is not a JWT.
 */
export function claimsOf(jwt: string): Record<string, unknown> | undefined {
  const payload = jwt.split('.')[1];
  if (!payload) return undefined;
  try {
    const parsed: unknown = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Check an ID token the token endpoint returned: issuer, audience, type, expiry, and the nonce
 * when the call was a sign-in.
 *
 * @param config - The session configuration.
 * @param idToken - The ID token.
 * @param nowSeconds - The current time, epoch seconds.
 * @param nonce - The transaction's nonce, for a sign-in; omitted for a refresh, whose token Cognito
 *   issues without one.
 * @returns The token's expiry, or undefined when any check fails.
 */
export function checkIdToken(
  config: SessionConfig,
  idToken: string,
  nowSeconds: number,
  nonce?: string
): number | undefined {
  const claims = claimsOf(idToken);
  if (!claims) return undefined;
  const {iss, aud, token_use: tokenUse, exp} = claims;
  if (iss !== config.issuer || aud !== config.clientId || tokenUse !== 'id') return undefined;
  if (typeof exp !== 'number' || exp <= nowSeconds) return undefined;
  if (nonce !== undefined && claims.nonce !== nonce) return undefined;
  return exp;
}

/**
 * The user a stored ID token names, in the browser's existing shape.
 *
 * The username comes from the configured claim, the one the API's verifier also reads, so the
 * prefixes the browser builds and the identity the API attributes a request to are the same name.
 *
 * @param config - The session configuration, for the username claim.
 * @param idToken - The ID token.
 * @returns The user, or undefined when the token carries no username.
 */
export function userOf(config: SessionConfig, idToken: string): SessionUser | undefined {
  const claims = claimsOf(idToken);
  const username = claims?.[config.usernameClaim];
  if (typeof username !== 'string' || username === '') return undefined;
  const email = claims?.email;
  return typeof email === 'string' ? {username, email} : {username};
}

/**
 * One POST to the token endpoint, classified, bounded by the token endpoint's deadline from the
 * request to the end of the body. Nothing about the request or the response body is logged, because
 * both carry credentials.
 *
 * @param config - The session configuration.
 * @param form - The form fields.
 * @param nowSeconds - The current time, epoch seconds.
 * @param nonce - The nonce to check, for a sign-in.
 * @returns The tokens, or why there are none.
 */
async function tokenRequest(
  config: SessionConfig,
  form: Record<string, string>,
  nowSeconds: number,
  nonce?: string
): Promise<TokenResult> {
  const bound = deadline(TOKEN_ENDPOINT_TIMEOUT_MS);
  try {
    return await tokenExchange(config, form, nowSeconds, bound.signal, nonce);
  } finally {
    bound.clear();
  }
}

/**
 * The token endpoint call and its classification, with the whole exchange, body included, under
 * one signal.
 *
 * @param config - The session configuration.
 * @param form - The form fields for the grant.
 * @param nowSeconds - The current time, epoch seconds.
 * @param signal - The deadline's signal.
 * @param nonce - The nonce to check, for a sign-in.
 * @returns The tokens, or why there are none.
 */
async function tokenExchange(
  config: SessionConfig,
  form: Record<string, string>,
  nowSeconds: number,
  signal: AbortSignal,
  nonce?: string
): Promise<TokenResult> {
  let response: Response;
  try {
    response = await fetch(config.tokenUrl, {
      method: 'POST',
      headers: {
        'content-type': 'application/x-www-form-urlencoded',
        authorization: basicAuthorization(config)
      },
      body: new URLSearchParams(form).toString(),
      redirect: 'manual',
      signal
    });
  } catch {
    return {ok: false, failure: 'unavailable'};
  }
  if (response.status >= 500) return {ok: false, failure: 'unavailable'};
  let body: Record<string, unknown>;
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    return {ok: false, failure: 'unavailable'};
  }
  if (!response.ok) {
    if (body.error === 'invalid_grant') return {ok: false, failure: 'invalid_grant'};
    if (body.error === 'invalid_client' || body.error === 'unauthorized_client')
      return {ok: false, failure: 'invalid_client'};
    return {ok: false, failure: 'rejected'};
  }
  const idToken = body.id_token;
  if (typeof idToken !== 'string') return {ok: false, failure: 'rejected'};
  const tokenExpiresAt = checkIdToken(config, idToken, nowSeconds, nonce);
  if (tokenExpiresAt === undefined) return {ok: false, failure: 'rejected'};
  const refreshToken = typeof body.refresh_token === 'string' ? body.refresh_token : undefined;
  return {ok: true, tokens: {idToken, tokenExpiresAt, refreshToken}};
}

/**
 * Exchange an authorization code, with the PKCE verifier and the client secret.
 *
 * @param config - The session configuration.
 * @param code - The authorization code.
 * @param transaction - The sign-in transaction the code belongs to.
 * @param nowSeconds - The current time, epoch seconds.
 * @returns The tokens, refresh token included, or why there are none.
 */
export function exchangeCode(
  config: SessionConfig,
  code: string,
  transaction: SignInTransaction,
  nowSeconds: number
): Promise<TokenResult> {
  return tokenRequest(
    config,
    {
      grant_type: 'authorization_code',
      code,
      redirect_uri: redirectUri(config),
      code_verifier: transaction.codeVerifier,
      client_id: config.clientId
    },
    nowSeconds,
    transaction.nonce
  );
}

/**
 * Refresh: a new ID token for a stored refresh token. With rotation off, the refresh token stays
 * valid and none comes back.
 *
 * @param config - The session configuration.
 * @param refreshToken - The stored refresh token.
 * @param nowSeconds - The current time, epoch seconds.
 * @returns The new ID token, or why there is none.
 */
export function refreshTokens(config: SessionConfig, refreshToken: string, nowSeconds: number): Promise<TokenResult> {
  return tokenRequest(
    config,
    {grant_type: 'refresh_token', refresh_token: refreshToken, client_id: config.clientId},
    nowSeconds
  );
}

/**
 * Revoke a refresh token. Best effort: the caller has already deleted the session.
 *
 * @param config - The session configuration.
 * @param refreshToken - The token to revoke.
 * @returns Whether the endpoint accepted the revocation.
 */
export async function revoke(config: SessionConfig, refreshToken: string): Promise<boolean> {
  const bound = deadline(TOKEN_ENDPOINT_TIMEOUT_MS);
  try {
    const response = await fetch(config.revokeUrl, {
      method: 'POST',
      headers: {'content-type': 'application/x-www-form-urlencoded', authorization: basicAuthorization(config)},
      body: new URLSearchParams({token: refreshToken}).toString(),
      redirect: 'manual',
      signal: bound.signal
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    bound.clear();
  }
}

/**
 * The provider's logout URL, which the browser navigates to after the server ends the session.
 *
 * @param config - The session configuration.
 * @returns The URL.
 */
export function logoutUrl(config: SessionConfig): string {
  const url = new URL(config.logoutUrl);
  url.search = new URLSearchParams({client_id: config.clientId, logout_uri: config.portalOrigin}).toString();
  return url.toString();
}
