import 'server-only';
import {SessionConfigError, sessionConfig, type SessionConfig} from './config';
import {
  SESSION_COOKIE,
  SIGNIN_COOKIE,
  clearedCookie,
  parseSignin,
  readCookie,
  sessionCookie,
  signinCookie
} from './cookies';
import {apiTarget, declaresTooMuch, forward, readBoundedBody} from './forward';
import {authorizeUrl, exchangeCode, logoutUrl, newTransaction} from './oidc';
import {fromThePortal, isSafeMethod} from './origin';
import {refusal} from './refusal';
import {createSession, endSession, isSessionId, loadSession, nowSeconds, sessionKey} from './session';
import type {SessionStore} from './session.types';
import {boundedSend, dynamoSessionStore} from './store';

/** What a handler runs on. Production builds it from the environment; tests pass doubles. */
export type SessionDeps = {config: SessionConfig; store: SessionStore};

/**
 * Build the dependencies from the server's environment, when a route runs.
 *
 * @returns The configuration and the DynamoDB store.
 * @throws SessionConfigError when a setting is unset.
 */
export function environmentDeps(): SessionDeps {
  const config = sessionConfig();
  return {config, store: dynamoSessionStore(config.tableName, boundedSend(config.region))};
}

/** A handler over its dependencies. */
type Handler = (request: Request, deps: SessionDeps) => Promise<Response>;

/**
 * Bind a handler to its dependencies, answering 503 when the configuration is incomplete.
 *
 * @param handler - The handler.
 * @param deps - How to build the dependencies; the environment by default.
 * @returns A route handler.
 */
export function route(
  handler: Handler,
  deps: () => SessionDeps = environmentDeps
): (request: Request) => Promise<Response> {
  return async (request) => {
    let resolved: SessionDeps;
    try {
      resolved = deps();
    } catch (error) {
      if (!(error instanceof SessionConfigError)) throw error;
      console.error(`session: ${error.variable} is unset, so the session routes are unavailable`);
      return refusal('ApiUnavailable', request.headers.get('x-request-id') ?? undefined);
    }
    return handler(request, resolved);
  };
}

/**
 * A redirect that is never cached, setting each cookie given.
 *
 * @param location - Where to, absolute, built from configuration.
 * @param cookies - `Set-Cookie` values.
 * @returns The response.
 */
function redirect(location: string, cookies: string[] = []): Response {
  const headers = new Headers({location, 'cache-control': 'no-store'});
  for (const cookie of cookies) headers.append('set-cookie', cookie);
  return new Response(null, {status: 302, headers});
}

/**
 * The request's own id, echoed in a refusal so a reported failure is findable.
 *
 * @param request - The request.
 * @returns The id, if the caller sent one.
 */
const requestIdOf = (request: Request): string | undefined => request.headers.get('x-request-id') ?? undefined;

/** `GET /auth/login`: start a sign-in. The transaction rides in a cookie, so the store sees nothing. */
export const login: Handler = async (_request, {config}) => {
  const transaction = newTransaction();
  return redirect(authorizeUrl(config, transaction), [signinCookie(transaction)]);
};

/**
 * `GET /auth/callback`: finish a sign-in, or land on the failure message.
 *
 * The sign-in cookie is cleared only when its `state` matched: a mismatch means it belongs to
 * another sign-in still in flight, and clearing it would fail that one too.
 */
export const callback: Handler = async (request, {config, store}) => {
  const params = new URL(request.url).searchParams;
  const failed = (clear: boolean) =>
    redirect(`${config.portalOrigin}/?signin=failed`, clear ? [clearedCookie(SIGNIN_COOKIE)] : []);

  const transaction = parseSignin(readCookie(request, SIGNIN_COOKIE));
  const state = params.get('state');
  if (!transaction || !state || state !== transaction.state) return failed(false);
  const code = params.get('code');
  if (params.get('error') !== null || !code) return failed(true);

  const now = nowSeconds();
  const exchanged = await exchangeCode(config, code, transaction, now);
  if (!exchanged.ok || exchanged.tokens.refreshToken === undefined) {
    console.error(
      `session: a sign-in's code exchange failed (${exchanged.ok ? 'no refresh token' : exchanged.failure})`
    );
    return failed(true);
  }

  let sessionId: string;
  try {
    sessionId = await createSession(
      store,
      config,
      {...exchanged.tokens, refreshToken: exchanged.tokens.refreshToken},
      now
    );
  } catch {
    console.error('session: the store did not take a new session');
    return failed(true);
  }
  const previous = readCookie(request, SESSION_COOKIE);
  if (isSessionId(previous)) {
    await store
      .delete(sessionKey(previous))
      .catch(() => console.error('session: a replaced session could not be deleted'));
  }
  return redirect(`${config.portalOrigin}/`, [sessionCookie(sessionId), clearedCookie(SIGNIN_COOKIE)]);
};

/** `POST /auth/logout`: end the session and answer the provider's logout URL. */
export const logout: Handler = async (request, {config, store}) => {
  if (!fromThePortal(request, config.portalOrigin)) return refusal('AccessDenied', requestIdOf(request));
  if (!(await endSession(store, config, readCookie(request, SESSION_COOKIE)))) {
    return refusal('ApiUnavailable', requestIdOf(request));
  }
  const headers = new Headers({'cache-control': 'no-store'});
  headers.append('set-cookie', clearedCookie(SESSION_COOKIE));
  return Response.json({logoutUrl: logoutUrl(config)}, {headers});
};

/** `GET /auth/session`: who is signed in, refreshing first when the token is near expiry. */
export const session: Handler = async (request, {config, store}) => {
  const loaded = await loadSession(store, config, readCookie(request, SESSION_COOKIE), {forceRefresh: false});
  if (loaded.status === 'absent') return refusal('SessionExpired', requestIdOf(request));
  if (loaded.status === 'unavailable') return refusal('ApiUnavailable', requestIdOf(request));
  return Response.json(loaded.user, {headers: {'cache-control': 'no-store'}});
};

/** `POST /auth/refresh`: refresh whatever the expiry, so newly granted claims arrive. */
export const refresh: Handler = async (request, {config, store}) => {
  if (!fromThePortal(request, config.portalOrigin)) return refusal('AccessDenied', requestIdOf(request));
  const loaded = await loadSession(store, config, readCookie(request, SESSION_COOKIE), {forceRefresh: true});
  if (loaded.status === 'absent') return refusal('SessionExpired', requestIdOf(request));
  if (loaded.status === 'unavailable') return refusal('ApiUnavailable', requestIdOf(request));
  return new Response(null, {status: 204, headers: {'cache-control': 'no-store'}});
};

/**
 * `/api/<rest>`: the API's same-origin pass-through.
 *
 * For an unsafe method the order is `Origin`, then the declared length, then the session, then the
 * body, so neither a forged request nor an oversized one costs a store read, and no body is read
 * for a caller who may not send one.
 */
export const api: Handler = async (request, {config, store}) => {
  const target = apiTarget(config.apiOrigin, request.url);
  if (target === undefined) return refusal('NotFound', requestIdOf(request));
  const unsafe = !isSafeMethod(request.method);
  if (unsafe && !fromThePortal(request, config.portalOrigin)) return refusal('AccessDenied', requestIdOf(request));
  if (declaresTooMuch(request)) return refusal('PayloadTooLarge', requestIdOf(request));

  const loaded = await loadSession(store, config, readCookie(request, SESSION_COOKIE), {forceRefresh: false});
  if (loaded.status === 'absent') return refusal('SessionExpired', requestIdOf(request));
  if (loaded.status === 'unavailable') return refusal('ApiUnavailable', requestIdOf(request));

  let body: Uint8Array<ArrayBuffer> | undefined;
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    const read = await readBoundedBody(request);
    if (read === 'too-large') return refusal('PayloadTooLarge', requestIdOf(request));
    body = read;
  }
  return forward(request, target, loaded.idToken, body);
};
