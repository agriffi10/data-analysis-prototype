import {getIdToken} from './awsCredentials';
import {configValue} from './runtimeConfig';
import type {ServiceResult} from '../types/service.types';

/**
 * The auth-shaped failures. The transport contract widens this union; these two
 * are settled here because they are the pair a user must be able to tell apart.
 *
 * `SessionExpired` means sign in again and it will work. `AccessDenied` means
 * signing in again cannot help. Rendering one wording for both is the defect this
 * split exists to prevent.
 */
export type ApiAuthCode = 'SessionExpired' | 'AccessDenied' | 'ApiUnavailable';

/** What a caller asks for. Deliberately thin — the transport contract widens it. */
export type ApiRequest = {
  /** Path under the API origin, beginning with a slash. */
  path: string;
  /** HTTP method. Defaults to GET. */
  method?: string;
};

/** How many times a 401 is retried. Exactly one, and it is the only retry in this app. */
const MAX_AUTH_RETRIES = 1;

/**
 * Resolve the API origin, or say why we cannot.
 *
 * The value carries NO trailing slash — the infrastructure builds it that way, and every path
 * below is joined to it directly. Nothing on this side would notice if that changed, so it is
 * written down here rather than left as a fact two repositories apart agree on by luck.
 *
 * `configValue` THROWS in a production build before the runtime document has loaded,
 * and `apiBaseUrl` is an optional key with no dev fallback — so it is legitimately
 * `undefined` on a laptop, in the test suite, and in any deployment predating the API.
 * Both are handled here rather than at the call site, because `apiFetch` promises never
 * to throw and the first thing it does is read this.
 */
function apiOrigin(): string | undefined {
  try {
    return configValue('apiBaseUrl');
  } catch {
    return undefined;
  }
}

/** The one failure shape, so no branch below can invent a second wording. */
function failure<T>(code: ApiAuthCode): ServiceResult<T> {
  return {success: false, error: {message: '', code}};
}

/**
 * The browser's one door to the API.
 *
 * Fetches the ID token per call and attaches it as a bearer; on any 401 it forces
 * exactly one token refresh and retries exactly once; it never throws, and no API or
 * provider text reaches a rendered string — the `code` carries the wording.
 *
 * THE TOKEN IS NEVER CACHED HERE. Amplify owns its lifecycle, including the silent
 * refresh, and a second cache in this module serves a stale token after one.
 *
 * THE 401 CAUSE IS NOT READ, because the API deliberately does not disclose it: every
 * refusal is byte-identical on purpose. That is why the retry is unconditional rather
 * than driven by a discriminator, and it is the whole of why one retry is enough.
 *
 * @param request - The path and method to call.
 * @returns The parsed body, or the machine code a surface maps to wording.
 */
export async function apiFetch<T>(request: ApiRequest): Promise<ServiceResult<T>> {
  const origin = apiOrigin();
  if (origin === undefined) return failure<T>('ApiUnavailable');

  for (let attempt = 0; attempt <= MAX_AUTH_RETRIES; attempt += 1) {
    // Forced on the retry only. A forced refresh on the first attempt would spend a
    // network round trip per call and defeat Amplify's own caching.
    const token = await getIdToken(attempt > 0);
    if (!token.success) return failure<T>('SessionExpired');

    let response: Response;
    try {
      response = await fetch(`${origin}${request.path}`, {
        method: request.method ?? 'GET',
        headers: {authorization: `Bearer ${token.data}`}
      });
    } catch {
      // A network failure, a timeout, a CORS refusal. NOT retried — the single retry
      // this module has belongs to the 401 path and to nothing else.
      return failure<T>('ApiUnavailable');
    }

    if (response.status === 401) continue;
    if (response.status === 403) return failure<T>('AccessDenied');
    if (!response.ok) return failure<T>('ApiUnavailable');

    try {
      return {success: true, data: (await response.json()) as T};
    } catch {
      return failure<T>('ApiUnavailable');
    }
  }

  // Every attempt 401'd. The refresh did not help, so the session is genuinely gone —
  // and there is no third request, which is what stops a dead refresh token spinning.
  return failure<T>('SessionExpired');
}
