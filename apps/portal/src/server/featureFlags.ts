import 'server-only';
import {headers} from 'next/headers';
import {GATED_SURFACES, firstEnabledDestination} from '../features/feature-flags/gatedSurfaces';
import {resolveFeatureFlagDocument} from '../features/feature-flags/resolveFeatureFlags';
import type {FeatureFlagKey, FeatureFlags, SeededFeatureFlags} from '../features/feature-flags/featureFlags.types';
import {API_ROUTES} from '../types/apiContract.generated';
import {renderRuntimeDocument} from './runtimeDocument';
import {SESSION_COOKIE, readCookieHeader} from './session/cookies';
import {deadline} from './session/deadline';
import {environmentDeps} from './session/handlers';
import {peekSession} from './session/session';

/** A held set younger than this is answered with no refresh. */
export const HELD_FRESH_MS = 60_000;

/** A held set older than this is never answered: the browser's own `staleTime` for the flags. */
export const HELD_MAX_AGE_MS = 60 * 60 * 1000;

/**
 * The oldest held set an area layout answers from. Shorter than the hour a page may be sent, because
 * a layout never refreshes the set and another task may hold an older one than the task that seeded
 * the tab: an "off" it held from before a flag was published on would otherwise override the tab's
 * newer "on" for up to an hour. Past this the gate answers `open` and the page's browser gate decides.
 */
export const GATE_MAX_AGE_MS = 5 * 60 * 1000;

/** How long a refresh waits on the API, answer and body together. */
export const REFRESH_DEADLINE_MS = 10_000;

/** After a failed refresh, how long before another may start, which bounds its log to one line a minute. */
export const REFRESH_FAILURE_PAUSE_MS = 60_000;

/** A refresh starts only on a token with at least this long left; a peek never refreshes one. */
export const REFRESH_TOKEN_MIN_LIFE_MS = 60_000;

/**
 * What the server keeps between requests: the held set, when the last refresh failed, and whether
 * one is in flight. Never a token, and nothing about a session: the document is the same for every
 * signed-in user, so one set serves them all.
 */
type HeldState = {held: SeededFeatureFlags | undefined; failedAt: number | undefined; refreshing: boolean};

/**
 * Where the state lives: on the process's global object rather than in this module, because Next
 * may evaluate a server module once per route entry and again on a dev reload, and an area layout
 * reading a copy the root layout never warmed would answer `open` for ever.
 */
const STATE = Symbol.for('dataquarry.serverFeatureFlags');

/** An area layout's answer: its page, or the "not available" page for the flag that is off. */
export type RouteGate =
  {kind: 'open'} | {kind: 'unavailable'; flag: FeatureFlagKey; fallback: FeatureFlagKey | undefined};

/**
 * The process's one held state, made on first use.
 *
 * @returns The state.
 */
function state(): HeldState {
  const scope = globalThis as typeof globalThis & {[STATE]?: HeldState};
  scope[STATE] ??= {held: undefined, failedAt: undefined, refreshing: false};
  return scope[STATE];
}

/**
 * Forget the held state, for a suite that needs a cold process between cases.
 *
 * @returns Nothing.
 */
export function resetServerFeatureFlagsForTests(): void {
  delete (globalThis as typeof globalThis & {[STATE]?: HeldState})[STATE];
}

/**
 * The flag set to send with the page, for the root layout: read once per document load.
 *
 * It costs the page one session-store read and never a call to the API or the provider: the set is
 * answered from what the server already holds, and a set that is stale or missing is refreshed in the
 * background with the requesting session's token, for a later page. A request with no session gets
 * nothing, so no flags are sent to a signed-out visitor.
 *
 * **It never rejects.** A throw in the root layout answers 500 on every page, so anything that throws,
 * an incomplete session configuration included, becomes `undefined` after one log line, and the
 * browser then reads the flags itself as it did before the server sent them.
 *
 * **A FLAG IS PRESENTATION, NEVER AUTHORIZATION**: nothing a request to the API passes through may
 * import this module, and a test holds that.
 *
 * @returns The held set and when the API answered it, or `undefined`.
 */
export async function serverFeatureFlags(): Promise<SeededFeatureFlags | undefined> {
  try {
    const cookie = readCookieHeader((await headers()).get('cookie'), SESSION_COOKIE);
    if (cookie === undefined) return undefined;
    const {config, store} = environmentDeps();
    const session = await peekSession(store, config, cookie);
    if (session.status !== 'active') return undefined;

    const {held} = state();
    if (!held || Date.now() - held.readAt >= HELD_FRESH_MS) {
      startRefresh(session.idToken, session.tokenExpiresAt, config.apiOrigin);
    }
    return heldFeatureFlags();
  } catch (error) {
    console.error(`feature flags: the server could not read its held set (${nameOf(error)})`);
    return undefined;
  }
}

/**
 * The held set, for the area layouts: synchronous, with no I/O, and no refresh, having no token to
 * start one with.
 *
 * @returns A copy of the held set when it is younger than an hour, `undefined` otherwise.
 */
export function heldFeatureFlags(): SeededFeatureFlags | undefined {
  const {held} = state();
  if (!held || Date.now() - held.readAt >= HELD_MAX_AGE_MS) return undefined;
  return {flags: {...held.flags}, readAt: held.readAt};
}

/**
 * Whether an area's page is answered by the server with the "not available" page.
 *
 * Read from the registry's `route` rows for that exact path, never from a constant in the layout, and
 * from the held set alone. With no held set younger than {@link GATE_MAX_AGE_MS}, or a fault of any
 * kind, it answers `open`, which leaves
 * the decision to the page's own browser gate: there is no error boundary between an area layout and
 * the root, so a throw here would answer 500.
 *
 * @param path - The area's path, as its layout sits in the tree (`/query`).
 * @returns `unavailable` with the flag that is off and the fallback's key, or `open`.
 */
export function serverRouteGate(path: string): RouteGate {
  try {
    const seeded = heldFeatureFlags();
    if (!seeded || Date.now() - seeded.readAt >= GATE_MAX_AGE_MS) return {kind: 'open'};
    const isEnabled = (key: FeatureFlagKey) => seeded.flags[key];
    for (const [key, surfaces] of Object.entries(GATED_SURFACES) as [FeatureFlagKey, typeof GATED_SURFACES.files][]) {
      if (!isEnabled(key) && surfaces.some((surface) => surface.kind === 'route' && surface.path === path)) {
        return {kind: 'unavailable', flag: key, fallback: firstEnabledDestination(isEnabled)};
      }
    }
    return {kind: 'open'};
  } catch (error) {
    console.error(`feature flags: the server could not decide a route gate (${nameOf(error)})`);
    return {kind: 'open'};
  }
}

/**
 * Start one background refresh, unless one is in flight, the last failed under a minute ago, or the
 * token is too near its expiry to be worth sending. Never awaited by the render.
 *
 * @param idToken - The requesting session's ID token.
 * @param tokenExpiresAt - Its expiry, epoch seconds.
 * @param apiOrigin - The API's origin.
 * @returns Nothing.
 */
function startRefresh(idToken: string, tokenExpiresAt: number, apiOrigin: string): void {
  const current = state();
  const now = Date.now();
  if (current.refreshing) return;
  if (current.failedAt !== undefined && now - current.failedAt < REFRESH_FAILURE_PAUSE_MS) return;
  if (tokenExpiresAt * 1000 - now < REFRESH_TOKEN_MIN_LIFE_MS) return;
  current.refreshing = true;
  void refresh(idToken, apiOrigin).finally(() => {
    current.refreshing = false;
  });
}

/**
 * Read the document through the API and hold what it resolves to, or keep the held set and record
 * the failure.
 *
 * The failure's log line names its reason and never the token or the body.
 *
 * @param idToken - The requesting session's ID token, held here and nowhere longer-lived.
 * @param apiOrigin - The API's origin.
 * @returns Nothing; never rejects.
 */
async function refresh(idToken: string, apiOrigin: string): Promise<void> {
  let outcome: {flags: FeatureFlags} | {reason: string};
  try {
    outcome = await readDocument(idToken, apiOrigin);
  } catch (error) {
    outcome = {reason: nameOf(error)};
  }
  const current = state();
  if ('flags' in outcome) {
    current.held = {flags: outcome.flags, readAt: Date.now()};
    current.failedAt = undefined;
    return;
  }
  current.failedAt = Date.now();
  console.error(`feature flags: a refresh failed (${outcome.reason})`);
}

/**
 * One read of `GET /v1/feature-flags`, as the browser makes it but with the session's token as the
 * bearer: the target checked to have the API's origin, no cache, no redirect followed, and the answer
 * and its body both under one deadline.
 *
 * @param idToken - The bearer.
 * @param apiOrigin - The API's origin.
 * @returns The resolved set, or the reason there is none.
 */
async function readDocument(idToken: string, apiOrigin: string): Promise<{flags: FeatureFlags} | {reason: string}> {
  const target = `${apiOrigin}${API_ROUTES['featureFlags.get'].path}`;
  if (new URL(target).origin !== new URL(apiOrigin).origin) return {reason: 'target'};

  const bound = deadline(REFRESH_DEADLINE_MS);
  try {
    let response: Response;
    try {
      response = await fetch(target, {
        headers: {authorization: `Bearer ${idToken}`},
        cache: 'no-store',
        redirect: 'manual',
        signal: bound.signal
      });
    } catch {
      return {reason: 'no answer'};
    }
    if (response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
      return {reason: 'redirect'};
    }
    if (!response.ok) return {reason: `status ${response.status}`};

    let envelope: unknown;
    try {
      envelope = await response.json();
    } catch {
      return {reason: bound.signal.aborted ? 'no answer' : 'envelope'};
    }
    if (typeof envelope !== 'object' || envelope === null || typeof (envelope as {body?: unknown}).body !== 'string') {
      return {reason: 'envelope'};
    }
    const resolved = resolveFeatureFlagDocument((envelope as {body: string}).body, renderRuntimeDocument().environment);
    return resolved.success ? {flags: resolved.data} : {reason: `document ${resolved.error.code ?? 'unusable'}`};
  } finally {
    bound.clear();
  }
}

/**
 * A thrown value's name for a log line, never its message, which may carry a value.
 *
 * @param error - What was thrown.
 * @returns Its `name`, or `unknown`.
 */
function nameOf(error: unknown): string {
  return error instanceof Error ? error.name : 'unknown';
}
