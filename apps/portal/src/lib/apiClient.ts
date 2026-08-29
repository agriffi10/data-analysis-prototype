import {API_ROUTES} from '../types/apiContract.generated';
import type {
  ApiErrorCode,
  ApiRouteId,
  ErrorParams,
  PathParamsOf,
  QueryOf,
  RequestOf,
  ResponseOf
} from '../types/apiContract.generated';
import {configValue} from './runtimeConfig';
import type {ServiceResult} from '../types/service.types';

/**
 * The codes this module mints. The server can produce none of them, deliberately: a timeout, an
 * unreachable network and a value that cannot be put in a URL are facts about this browser, not
 * answers from an API.
 *
 * `UnsendableParameter` is the third and it is minted for a request that was never sent — see
 * `substitute`. It is deliberately NOT the server's `InvalidRequest`: reusing that would make a
 * refusal of ours indistinguishable from the API's own, in the one case where the difference is
 * the whole diagnosis.
 *
 * They are NOT in the generated enum, and a guard asserts all three sets stay disjoint — the
 * generated codes, these, and `errorMessages`' passthrough codes.
 */
export type ApiClientCode = 'RequestTimeout' | 'NetworkUnavailable' | 'UnsendableParameter';

/**
 * The API function's own timeout. Mirrored from `cpcommon.jwks`, and pinned to it by a test that
 * reads the Python rather than trusting this copy.
 */
export const API_FUNCTION_TIMEOUT_SECONDS = 29;

/**
 * AWS's hard ceiling on an HTTP API integration. Not raisable, which is what makes the ordering
 * below a property rather than a preference.
 */
export const API_GATEWAY_INTEGRATION_CEILING_SECONDS = 30;

/**
 * How long this client waits, and it is deliberately ABOVE the function's own timeout.
 *
 * The order is the whole point: the *server* gives up first, so an abort here always means a
 * genuinely dead connection rather than a request the server is still completing. A shorter
 * client timeout aborts work the server then finishes — which for a write is a mutation the user
 * has been told failed.
 */
export const TIMEOUT_MS = API_GATEWAY_INTEGRATION_CEILING_SECONDS * 1000;

/** How many times a 401 is retried. Exactly one, and it is the only retry in this app. */
const MAX_AUTH_RETRIES = 1;

type TokenProvider = (forceRefresh: boolean) => Promise<string | null>;

let tokenProvider: TokenProvider | undefined;
let unauthenticatedHandler: (() => void) | undefined;

/**
 * Register where the bearer comes from. Called once, by the composition root.
 *
 * Injected rather than imported so this module has no opinion about how a session is obtained —
 * the auth feature owns that, including the forced refresh — and so a test can drive the
 * no-session arm without a Cognito stub.
 *
 * The provider takes `forceRefresh` because the 401 path needs a *forced* refresh, which is the
 * browser's only token-refresh path. A no-argument provider cannot express it, and reaching
 * around the seam to force it would make the seam decorative.
 *
 * @param provider - Returns a bearer, or `null` when there is no usable session.
 * @returns None.
 */
export function setAuthTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider;
}

/**
 * Register what happens when a 401 SURVIVES the single refresh-and-retry.
 *
 * `apiRequest` itself never navigates. A service that navigates makes every test touching a 401 a
 * navigation test, and makes a background refetch able to throw a user out of a half-filled form.
 *
 * @param handler - Called once per genuinely-dead session.
 * @returns None.
 */
export function setUnauthenticatedHandler(handler: () => void): void {
  unauthenticatedHandler = handler;
}

/** Test seam: forget both registrations, so a suite starts from the unregistered state. */
export function resetApiClientForTests(): void {
  tokenProvider = undefined;
  unauthenticatedHandler = undefined;
}

/**
 * Whether a route may be retried above this client.
 *
 * The ONLY source of a TanStack Query `retry` value for an API-backed hook. Idempotency is a
 * property of the route, declared in the contract, so a hook cannot decide it locally and be
 * wrong — the Data Explorer once carried `retry: 1` on a billed, stateful `StartQueryExecution`
 * because it looked like a read.
 *
 * @param route - The route id.
 * @returns `false` for anything not declared idempotent; a retry count otherwise.
 */
export function apiRetryPolicy(route: ApiRouteId): false | number {
  return API_ROUTES[route].idempotent ? 1 : false;
}

/** What a caller may pass. A route id, never a URL — see the module's one-door rule. */
export type ApiRequestOptions<R extends ApiRouteId> = {
  body?: RequestOf<R>;
  // Generated from the route's own declaration, not `Record<string, string>`. Untyped, a
  // misspelled or missing key is a runtime 400 the handler never sees; typed, it is a `tsc -b`
  // failure at the call site. The declaration is all-strings by construction — the contract
  // refuses a query field that is not one, because a query string cannot carry anything else.
  query?: QueryOf<R> extends null ? never : QueryOf<R>;
  // Same reasoning as `query`, one step stronger: a route with a fixed path declares no
  // parameters, so `PathParamsOf` is `{}` — which accepts any object — and passing one has to be
  // refused by the type rather than ignored at runtime.
  params?: keyof PathParamsOf<R> extends never ? never : PathParamsOf<R>;
  signal?: AbortSignal;
};

/**
 * What `apiRequest` takes after the route id.
 *
 * A rest tuple rather than an optional parameter, and the shape is load-bearing: a templated
 * route makes the options object REQUIRED and its `params` required within it, so forgetting the
 * parameter is `TS2554` at the call site. Written as `options?: ApiRequestOptions<R>` with an
 * optional `params`, the omission compiles — and at runtime the literal `/v1/queries/{id}` goes
 * on the wire, the gateway decodes the braces, the server's matcher MATCHES, and the service
 * receives a 400 about an execution id nobody typed. That path looked unreachable and was not.
 *
 * A generic wrapper over `apiRequest` must forward `...args: ApiRequestArgs<R>` rather than take
 * an options object: with `R` still a type variable, TypeScript cannot pick an arm of the
 * conditional, so a wrapper that passes nothing does not compile.
 */
type ApiRequestArgs<R extends ApiRouteId> = keyof PathParamsOf<R> extends never
  ? [options?: ApiRequestOptions<R>]
  : [options: ApiRequestOptions<R> & {params: PathParamsOf<R>}];

/**
 * The browser's one door to the API.
 *
 * Takes a ROUTE ID from the generated table rather than a path: a service that builds a URL is
 * outside the contract, outside the retry rule and outside the type that says what comes back.
 *
 * It never throws, and no server text reaches a rendered string — the `code` carries the wording,
 * which `lib/errorMessages.ts` resolves. The server's `detail` is operator text and goes to the
 * dev console alone.
 *
 * @param route - The route id.
 * @param args - The body, path parameters, query parameters and caller abort signal. Required for
 *   a templated route, optional for a fixed one — see `ApiRequestArgs`.
 * @returns The parsed payload, or the machine code a surface maps to wording.
 */
export async function apiRequest<R extends ApiRouteId>(
  route: R,
  ...args: ApiRequestArgs<R>
): Promise<ServiceResult<ResponseOf<R>>> {
  const options: ApiRequestOptions<R> = args[0] ?? {};
  const origin = apiOrigin();
  // Legitimately absent on a laptop and in the test suite; in production the app refuses to boot
  // without it, so this arm cannot reach a user.
  if (origin === undefined) return failure('ApiUnavailable');

  const {method, path} = API_ROUTES[route];
  const filled = substitute(path, options.params as Record<string, string> | undefined);
  // A value the path cannot carry never goes on the wire — see `substitute`. Refused rather than
  // sent, because what it would reach is a different route answering 200.
  if (filled === undefined) return failure('UnsendableParameter');
  const url = `${origin}${filled}${queryString(options.query as Record<string, string> | undefined)}`;

  for (let attempt = 0; attempt <= MAX_AUTH_RETRIES; attempt += 1) {
    if (!tokenProvider) return failure('SessionExpired');
    // Forced on the retry only: a forced refresh on every first attempt spends a network round
    // trip per call and defeats the provider's own caching.
    const token = await tokenProvider(attempt > 0);
    if (!token) {
      // A FORCED refresh returning nothing is the same condition as a 401 surviving the retry —
      // the session is gone — so it takes the same exit. On the first attempt it is not: that is
      // an ordinary not-signed-in-yet call, and firing the handler there would act on every
      // mount before sign-in completes.
      if (attempt > 0) unauthenticatedHandler?.();
      return failure('SessionExpired');
    }

    const outcome = await send(url, method, token, options);
    if (outcome.status !== 401) return outcome.result;
  }

  // Both attempts 401'd, so the refresh did not help and the session is genuinely gone. There is
  // no third request, which is what stops a dead refresh token spinning.
  unauthenticatedHandler?.();
  return failure('SessionExpired');
}

/** Read at CALL time, never captured at module load: the document is not in hand until boot. */
function apiOrigin(): string | undefined {
  try {
    // No trailing slash — the infrastructure builds it that way and every path is joined
    // directly, so it is written down here rather than left as luck between two repositories.
    return configValue('apiBaseUrl');
  } catch {
    return undefined;
  }
}

/**
 * Fill a path template's placeholders, encoding each value — or refuse a value that is not ONE
 * path segment.
 *
 * The property is "this is a single segment", not "this has no slash", and the difference is
 * load-bearing because **two unrelated mechanisms turn a value into extra structure, at two
 * different layers**:
 *
 * - `a/b` survives `encodeURIComponent` as `%2F`, reaches the wire intact, and is decoded by API
 *   Gateway (measured: `/health%7A` matched `/healthz` against the deployed API).
 * - `.` and `..` are not encoded at all — `encodeURIComponent('.') === '.'` — and never reach the
 *   wire in the first place: the URL parser collapses dot segments when `fetch` reads the string.
 *
 * Either way the request addresses a template it did not name. `athena.status` asked for
 * `abc/results` — or for `.` — arrives as `athena.results`; `catalog.database.get` for
 * `alice/tables` arrives as `catalog.tables.list`. Both answer 200, with a body of the wrong
 * shape, typed as the right one. A 404 would have been survivable; this is not.
 *
 * It is refused here because the server cannot tell such a path from one a caller legitimately
 * typed — by the time it matches, the separator is a separator. That is about where the check can
 * work, not about safety: both routes sit on the same plane under the same assumed identity, so a
 * caller reaches nothing they could not have requested directly.
 *
 * Every value this app passes is a catalog identifier, so this refuses nothing today. It is here
 * because the next caller is the one that would find it.
 */
function substitute(path: string, params: Record<string, string> | undefined): string | undefined {
  if (!params) return path;
  // `typeof` first, and not only for the empty case: a `string` that is `undefined` at runtime
  // arrives through any cast, and this module's contract is that it never throws.
  const unsendable = (value: string) =>
    typeof value !== 'string' || value === '' || value === '.' || value === '..' || value.includes('/');
  if (Object.values(params).some(unsendable)) return undefined;
  return path.replace(/\{([^}]+)\}/g, (whole, name: string) =>
    Object.hasOwn(params, name) ? encodeURIComponent(params[name]) : whole
  );
}

/** URL-encoded, always. S3 continuation tokens carry `+`, `/` and `=`, and `+` decodes to a space. */
function queryString(query: Record<string, string> | undefined): string {
  if (!query) return '';
  const encoded = new URLSearchParams(query).toString();
  return encoded ? `?${encoded}` : '';
}

async function send<R extends ApiRouteId>(
  url: string,
  method: string,
  token: string,
  options: ApiRequestOptions<R>
): Promise<{status: number; result: ServiceResult<ResponseOf<R>>}> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  // The caller's signal and the deadline both abort this request, and neither cancels the other:
  // an unmounted component and a dead connection are different reasons for the same stop.
  const onCallerAbort = () => controller.abort();
  // Checked as well as listened for: the token is awaited before this runs, so a caller that
  // aborts in that window has already fired its event and no listener would ever see it.
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener('abort', onCallerAbort);

  try {
    const response = await fetch(url, {
      method,
      // Explicit, so a cookie that appears on this domain for any reason is never sent. There is
      // no ambient credential in this design, and therefore no CSRF surface to go with one.
      credentials: 'omit',
      signal: controller.signal,
      headers: {
        authorization: `Bearer ${token}`,
        'x-request-id': requestId(),
        ...(options.body === undefined ? {} : {'content-type': 'application/json'})
      },
      ...(options.body === undefined ? {} : {body: JSON.stringify(options.body)})
    });
    return {status: response.status, result: await interpret<R>(response)};
  } catch (err) {
    // A CORS failure is INDISTINGUISHABLE from a network failure here — the browser hands `fetch`
    // an opaque TypeError either way — so a mis-set allowed origin presents to a user as "the API
    // is down". That is why the origin list is asserted against a real preflight, not inferred
    // from the app working.
    const aborted = (err as {name?: string})?.name === 'AbortError';
    return {status: 0, result: failure(aborted ? 'RequestTimeout' : 'NetworkUnavailable')};
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', onCallerAbort);
  }
}

async function interpret<R extends ApiRouteId>(response: Response): Promise<ServiceResult<ResponseOf<R>>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }

  if (response.ok) {
    if (body === undefined || body === null || typeof body !== 'object') {
      return failure('ApiUnavailable');
    }
    return {success: true, data: body as ResponseOf<R>};
  }

  const envelope = (body as {error?: {code?: unknown; detail?: unknown; params?: unknown}} | undefined)?.error;
  if (envelope && typeof envelope.code === 'string') {
    logDetail(envelope.code, envelope.detail);
    // `params` is carried; `detail` is not. The detail is operator prose and the browser renders
    // no server sentence — the params are the structured half a service needs to mint the wording
    // it already owns.
    return failure(envelope.code as ApiErrorCode, envelope.params as ErrorParams | undefined);
  }

  // NOT envelope-shaped, and never parsed for text. API Gateway's own errors — its 413 at the
  // payload limit, a 429 under account throttling, a 502/504 on an invocation failure — are
  // produced ABOVE the router and carry AWS's wording, which no surface may render.
  return failure(byStatus(response.status));
}

function byStatus(status: number): ApiErrorCode {
  if (status === 413) return 'PayloadTooLarge';
  if (status === 429) return 'RateLimited';
  if (status === 404) return 'NotFound';
  if (status === 403) return 'AccessDenied';
  if (status === 401) return 'SessionExpired';
  if (status === 400) return 'InvalidRequest';
  // Everything else, named rather than left to fall through: a status with no mapping would
  // reach `toUserMessage` as `undefined` and resolve to the generic wording by accident rather
  // than by decision.
  return 'ApiUnavailable';
}

/**
 * The server's operator text, to the dev console and nowhere else.
 *
 * It is English written for whoever reads a log, never a sentence for a user — so it must not
 * reach `ServiceResult.error.message`, which is what a surface renders.
 */
function logDetail(code: string, detail: unknown): void {
  if (import.meta.env.DEV && typeof detail === 'string' && detail !== '') {
    console.warn(`[apiClient] ${code}: ${detail}`);
  }
}

/**
 * The failure shape, built in ONE place so no branch can invent a second wording.
 *
 * `message` is deliberately empty: the wording is chosen client-side from the code, by
 * `lib/errorMessages.ts`. A message authored here would be a second source of user-facing text.
 */
function failure<T>(code: ApiErrorCode | ApiClientCode, params?: ErrorParams): ServiceResult<T> {
  return {success: false, error: {message: '', code, ...(params ? {params} : {})}};
}

function requestId(): string {
  return crypto.randomUUID();
}
