import {vi} from 'vitest';
import type {ApiRouteId} from '../types/apiContract.generated';
import type {ServiceResult} from '../types/service.types';

/**
 * The one place a test programs `apiRequest`, now that the services call it instead of S3.
 *
 * Before the port these suites mocked `getS3Client` and asserted on SDK command inputs. The
 * service boundary moved, so the mock boundary moved with it — the repo's rule is to mock the
 * service boundary and nothing inside it, and the boundary is the API.
 *
 * **Programmed BY ROUTE ID, never by call order.** A service that stopped calling a route, or
 * started calling a different one, still satisfies an order-based mock — which is the shape of a
 * port that silently drops a request. Here an unprogrammed route throws, so a test only passes
 * against the calls it actually named.
 *
 * @example
 * const api = mockApi();
 * api.on('objects.readContent', {success: true, data: {body: '{}', etag: 'e'}});
 * // …drive the service…
 * expect(api.queryFor('objects.readContent')).toMatchObject({spaceName: 'alice', key: 'k'});
 */
export type ApiCall = {route: ApiRouteId; body?: unknown; query?: Record<string, string>};

export type ApiMock = {
  /** Programs one route's answer. Later calls replace earlier ones. */
  on: (route: ApiRouteId, result: ServiceResult<unknown>) => void;
  /** Programs a route to answer differently on each successive call. */
  onEach: (route: ApiRouteId, results: ServiceResult<unknown>[]) => void;
  /** Every call made, in order. */
  calls: ApiCall[];
  /** Route ids called, in order — the cheapest assertion for "what did this do". */
  routes: () => ApiRouteId[];
  /** The body of the first call to a route. */
  bodyFor: (route: ApiRouteId) => unknown;
  /** The query of the first call to a route. */
  queryFor: (route: ApiRouteId) => Record<string, string> | undefined;
  /** How many times a route was called. */
  countOf: (route: ApiRouteId) => number;
  /** The underlying vi mock, for the rare assertion that needs it. */
  fn: ReturnType<typeof vi.fn>;
};

/**
 * Builds the mock. Call inside `beforeEach`, after `vi.mock('../../lib/apiClient', …)`.
 *
 * @param apiRequest - The mocked `apiRequest` function, from `vi.mocked(...)`.
 * @returns The programmable mock.
 */
export function mockApi(apiRequest: ReturnType<typeof vi.fn>): ApiMock {
  const answers = new Map<string, ServiceResult<unknown>[]>();
  const calls: ApiCall[] = [];

  apiRequest.mockImplementation(async (route: ApiRouteId, options?: {body?: unknown; query?: Record<string, string>}) => {
    calls.push({route, body: options?.body, query: options?.query});
    const queued = answers.get(route);
    if (!queued || queued.length === 0) {
      throw new Error(
        `apiRequest('${route}') was called but no answer was programmed. ` +
          `Programmed: ${[...answers.keys()].join(', ') || 'none'}.`
      );
    }
    return queued.length === 1 ? queued[0] : queued.shift();
  });

  return {
    on: (route, result) => answers.set(route, [result]),
    onEach: (route, results) => answers.set(route, [...results]),
    calls,
    routes: () => calls.map((call) => call.route),
    bodyFor: (route) => calls.find((call) => call.route === route)?.body,
    queryFor: (route) => calls.find((call) => call.route === route)?.query,
    countOf: (route) => calls.filter((call) => call.route === route).length,
    fn: apiRequest
  };
}

/** A successful document read, for the seven services that read one. */
export function documentBody(value: unknown, etag = 'etag-1'): ServiceResult<{body: string; etag: string}> {
  return {
    success: true,
    data: {body: typeof value === 'string' ? value : JSON.stringify(value), etag}
  };
}

/** A failure carrying a machine code, the shape `apiRequest` returns. */
export function apiFailure(code: string): ServiceResult<never> {
  return {success: false, error: {message: '', code}};
}
