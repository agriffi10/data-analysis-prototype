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
 * How long this client waits, and it is deliberately ABOVE the server's worst path.
 *
 * The order is the whole point: the *server* gives up first, so an abort here always means a
 * genuinely dead connection rather than a request the server is still completing. A shorter client
 * timeout aborts work the server then finishes, which for a write is a mutation the user has been
 * told failed. The portal server's `/api/` route sits between this client and the API, and before it
 * forwards it may read the session, lose a refresh's write and read it again (three store calls), and
 * call the token endpoint once; then it waits for the API. A test sums those bounds from the server's
 * own constants and holds this above them.
 */
export const TIMEOUT_MS = 50_000;

/** The header naming the user this tab believes is signed in; the server refuses a request it does not match. */
const TAB_USER_HEADER = 'x-dq-user';

let unauthenticatedHandler: (() => void) | undefined;
let signedInUser: string | null = null;

/**
 * Record which user this tab holds, or that it holds none.
 *
 * One cookie serves every tab, so a tab whose user signed out while someone else signed in elsewhere
 * would otherwise act as the newcomer. Every request names this user, and the server refuses one that
 * names someone else; with none recorded, nothing is sent at all. The auth provider calls this before it
 * publishes a change of user, so a query the change starts already sees it.
 *
 * @param username - The signed-in user's username, from the claim the server and the API are
 *   configured to read, or null when the tab is signed out.
 * @returns None.
 */
export function setSignedInUser(username: string | null): void {
  signedInUser = username;
}

/**
 * Register what happens when the server answers 401, which means the session is gone or belongs to
 * someone else: the server refreshes tokens itself, so nothing the browser could retry would help.
 *
 * `apiRequest` itself never navigates. A service that navigates makes every test touching a 401 a
 * navigation test, and makes a background refetch able to throw a user out of a half-filled form.
 *
 * @param handler - Called once per 401, or undefined to stop calling anything.
 * @returns None.
 */
export function setUnauthenticatedHandler(handler: (() => void) | undefined): void {
  unauthenticatedHandler = handler;
}

/** Test seam: forget the handler and the held user, so a suite starts from the unregistered state. */
export function resetApiClientForTests(): void {
  unauthenticatedHandler = undefined;
  signedInUser = null;
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
  // No user, no request: a tab that has not learnt who is signed in, or has just learnt that nobody
  // is, has no name to send, and the server would refuse the request anyway.
  if (signedInUser === null) return failure('SessionExpired');

  const {method, path} = API_ROUTES[route];
  const filled = substitute(path, options.params as Record<string, string> | undefined);
  // A value the path cannot carry never goes on the wire — see `substitute`. Refused rather than
  // sent, because what it would reach is a different route answering 200.
  if (filled === undefined) return failure('UnsendableParameter');
  // Relative, so it resolves on the page's own origin, where the portal server's `/api/` route
  // attaches the session's token.
  const url = `/api${filled}${queryString(options.query as Record<string, string> | undefined)}`;

  const outcome = await send(url, method, signedInUser, options);
  if (outcome.status !== 401) return outcome.result;
  // The server refreshes the token before it forwards, so a 401 means the session is gone, or the
  // browser's cookie now belongs to another user. One request, and no retry.
  unauthenticatedHandler?.();
  return failure('SessionExpired');
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
  username: string,
  options: ApiRequestOptions<R>
): Promise<{status: number; result: ServiceResult<ResponseOf<R>>}> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  // The caller's signal and the deadline both abort this request, and neither cancels the other:
  // an unmounted component and a dead connection are different reasons for the same stop.
  const onCallerAbort = () => controller.abort();
  // Checked as well as listened for: a caller that aborted before this ran has already fired its
  // event, and no listener would ever see it.
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener('abort', onCallerAbort);

  try {
    const response = await fetch(url, {
      method,
      // The session cookie is the credential, and only this origin's server ever sees it. Its
      // unsafe methods are refused unless `Origin` names the portal, and every request must name the
      // tab's user, which a cross-site page cannot do.
      credentials: 'same-origin',
      signal: controller.signal,
      headers: {
        'x-request-id': requestId(),
        [TAB_USER_HEADER]: encodeURIComponent(username),
        ...(options.body === undefined ? {} : {'content-type': 'application/json'})
      },
      ...(options.body === undefined ? {} : {body: JSON.stringify(options.body)})
    });
    return {status: response.status, result: await interpret<R>(response)};
  } catch (err) {
    // The browser hands `fetch` an opaque TypeError for any failure to reach this origin's server.
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
