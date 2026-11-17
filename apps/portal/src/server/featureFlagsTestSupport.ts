import 'server-only';
import {headers} from 'next/headers';
import {vi} from 'vitest';
import type {FeatureFlags} from '../features/feature-flags/featureFlags.types';
import {FEATURE_FLAG_DEFAULTS} from '../features/feature-flags/featureFlagDefaults';
import {resetServerFeatureFlagsForTests, serverFeatureFlags} from './featureFlags';
import {SESSION_COOKIE} from './session/cookies';
import {environmentDeps} from './session/handlers';
import {storedSession, testDeps} from './session/testSupport';

/**
 * Support for the suites that need a held flag set: the server module's own and the area layouts'.
 * A suite using it mocks `next/headers` and `./session/handlers` (as its own path reaches them), so
 * the calls below program those mocks.
 */

/** The API's answer, as the server's refresh reads it: the envelope's `body` holds the document's text. */
export function envelope(document: unknown): Response {
  return answer(200, {body: JSON.stringify(document), etag: 'etag-1'});
}

/**
 * A response the refresh can read under a fake clock: `json()` resolves on a microtask, where a real
 * body stream may wait on a timer the fake clock holds.
 *
 * @param status - The status.
 * @param body - What `json()` answers.
 * @returns The response.
 */
export function answer(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    type: 'basic',
    json: async () => body
  } as unknown as Response;
}

/** A version-1 document whose defaults are every flag on, then `flags`. */
export function flagDocument(flags: Partial<FeatureFlags> = {}) {
  return {version: 1, defaults: {...FEATURE_FLAG_DEFAULTS, ...flags}, environments: {}};
}

/** Let a background refresh run to its end: it awaits only microtasks once its fetch has answered. */
export async function settle(): Promise<void> {
  for (let turn = 0; turn < 25; turn += 1) await Promise.resolve();
}

/**
 * A signed-in request: a stored session, the cookie naming it on the mocked `headers()`, and the
 * mocked dependencies over that store.
 *
 * @param overrides - Fields of the stored session to replace.
 * @returns The dependencies and the stored session.
 */
export async function signedInRequest(overrides: Parameters<typeof storedSession>[0] = {}) {
  const deps = testDeps();
  const session = storedSession(overrides);
  await deps.store.put(session.item);
  vi.mocked(environmentDeps).mockReturnValue(deps);
  vi.mocked(headers).mockResolvedValue(new Headers({cookie: `${SESSION_COOKIE}=${session.cookie}`}) as never);
  return {deps, ...session};
}

/**
 * Hold `flags` as the server's set, read through the real refresh path, then stop answering fetches.
 *
 * @param flags - The flags to turn from the all-on defaults.
 * @returns Nothing.
 */
export async function holdFlags(flags: Partial<FeatureFlags>): Promise<void> {
  resetServerFeatureFlagsForTests();
  await signedInRequest();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => envelope(flagDocument(flags)))
  );
  await serverFeatureFlags();
  await settle();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new Error('no request is expected once the set is held');
    })
  );
}
