import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  apiRequest,
  apiRetryPolicy,
  resetApiClientForTests,
  setSignedInUser,
  setUnauthenticatedHandler
} from './apiClient';
import {API_ROUTES} from '../types/apiContract.generated';
import {toUserText} from './errorMessages';

const fetchMock = vi.fn();

/** A response with a JSON body, as `fetch` would hand it back. */
function json(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body
  } as unknown as Response;
}

/** A response whose body is not JSON at all — a gateway's HTML error page, or nothing. */
function opaque(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new SyntaxError('Unexpected token < in JSON');
    }
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  setSignedInUser('ana maría');
});

afterEach(() => {
  fetchMock.mockReset();
  resetApiClientForTests();
  vi.unstubAllGlobals();
});

describe('apiRequest — the call it makes', () => {
  it('builds the URL from the ROUTE ID, never from a path a caller passed', async () => {
    fetchMock.mockResolvedValue(json(200, {usernames: [], generatedAt: null}));

    await apiRequest('userDirectory.get');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api${API_ROUTES['userDirectory.get'].path}`);
    expect(init.method).toBe('GET');
  });

  it("sends this origin's cookie, the tab's user and a request id, and no bearer", async () => {
    fetchMock.mockResolvedValue(json(200, {}));

    await apiRequest('userDirectory.get');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1];
    expect(init.credentials).toBe('same-origin');
    expect(init.headers['x-dq-user']).toBe('ana%20mar%C3%ADa');
    expect(init.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/);
    expect(init.headers).not.toHaveProperty('authorization');
  });

  it('sends no content-type when there is no body', async () => {
    fetchMock.mockResolvedValue(json(200, {}));

    await apiRequest('userDirectory.get');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1].headers['content-type']).toBeUndefined();
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
  });
});

describe('apiRequest — no user held', () => {
  it('returns SessionExpired and issues ZERO requests, and calls no handler', async () => {
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    setSignedInUser(null);

    const result = await apiRequest('userDirectory.get');

    expect(result).toMatchObject({success: false, error: {code: 'SessionExpired'}});
    expect(fetchMock).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('apiRequest — the 401 path', () => {
  it('is ONE request, one call of the handler, and SessionExpired, because the server already refreshed', async () => {
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    fetchMock.mockResolvedValue(json(401, {error: {code: 'SessionExpired', requestId: 'r1'}}));

    const result = await apiRequest('userDirectory.get');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({success: false, error: {code: 'SessionExpired'}});
  });
});

describe('apiRequest — the retry rule', () => {
  it.each([
    ['a 429', () => fetchMock.mockResolvedValue(json(429, {error: {code: 'RateLimited', requestId: 'r'}}))],
    ['a 503', () => fetchMock.mockResolvedValue(json(503, {error: {code: 'ApiUnavailable', requestId: 'r'}}))],
    ['a 500', () => fetchMock.mockResolvedValue(json(500, {error: {code: 'InternalError', requestId: 'r'}}))],
    ['a timeout', () => fetchMock.mockRejectedValue(Object.assign(new Error('aborted'), {name: 'AbortError'}))],
    ['a network failure', () => fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))]
  ])('issues exactly one request for %s', async (_label, respond) => {
    respond();

    await apiRequest('userDirectory.get');

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns false for every route the contract does not declare idempotent', () => {
    // Enumerated from the generated table, so a route added later is covered without this test
    // being edited.
    for (const [id, route] of Object.entries(API_ROUTES)) {
      const policy = apiRetryPolicy(id as keyof typeof API_ROUTES);
      if (!route.idempotent) expect(policy).toBe(false);
      else expect(policy).toBe(1);
    }
  });

  it('refuses to retry a NON-idempotent route, driven rather than waited for', () => {
    // The enumeration above cannot reach this arm: the contract declares one route today and it
    // is idempotent, so `return 1` unconditionally passes it. That is the exact incident FR-008
    // names — a retry on something that looked like a read and was a billed, stateful action — so
    // the arm is driven with a route of this test's own rather than left until SPEC-198 supplies
    // one.
    const table = API_ROUTES as unknown as Record<string, {method: string; path: string; idempotent: boolean}>;
    table['test.write'] = {method: 'POST', path: '/v1/test-write', idempotent: false};
    try {
      expect(apiRetryPolicy('test.write' as keyof typeof API_ROUTES)).toBe(false);
    } finally {
      delete table['test.write'];
    }
  });
});

describe('apiRequest — failures that are not envelopes', () => {
  it.each([
    [413, 'PayloadTooLarge'],
    [429, 'RateLimited'],
    [502, 'ApiUnavailable'],
    [504, 'ApiUnavailable']
  ])('maps a gateway %s by STATUS, never by parsing it for text', async (status, code) => {
    // API Gateway's own errors are produced ABOVE the router, carry AWS's wording and are not
    // envelope-shaped. A client that assumed every non-2xx was an envelope would throw a
    // SyntaxError the first time the gateway answered.
    fetchMock.mockResolvedValue(json(status, {message: 'Forbidden'}));

    const result = await apiRequest('userDirectory.get');

    expect(result).toMatchObject({success: false, error: {code}});
    expect(JSON.stringify(result)).not.toContain('Forbidden');
  });

  it('does not throw on an HTML error page or an empty body', async () => {
    for (const status of [413, 429, 502, 504]) {
      fetchMock.mockResolvedValue(opaque(status));
      await expect(apiRequest('userDirectory.get')).resolves.toMatchObject({success: false});
    }
  });
});

describe('apiRequest — the wording boundary', () => {
  it('carries the server code VERBATIM and never the server detail', async () => {
    fetchMock.mockResolvedValue(
      json(403, {
        error: {code: 'AccessDenied', requestId: 'r1', detail: 'DISTINCTIVE-OPERATOR-MARKER'}
      })
    );

    const result = await apiRequest('userDirectory.get');

    expect(result).toMatchObject({success: false, error: {code: 'AccessDenied'}});
    expect(JSON.stringify(result)).not.toContain('DISTINCTIVE-OPERATOR-MARKER');
    expect(result.success === false && result.error.message).toBe('');
  });

  it('resolves an unrecognised code to the generic wording', async () => {
    // The deploy-skew case: the API deploys before the SPA image, so an old bundle WILL meet a
    // code it has no rule for.
    fetchMock.mockResolvedValue(json(400, {error: {code: 'SomeCodeFromANewerApi', requestId: 'r1'}}));

    const result = await apiRequest('userDirectory.get');

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(toUserText(result.error)).toBe('Something went wrong. Contact the Administrator.');
  });
});

describe('the timeout', () => {
  it('produces RequestTimeout when the request is aborted', async () => {
    fetchMock.mockRejectedValue(Object.assign(new Error('aborted'), {name: 'AbortError'}));

    const result = await apiRequest('userDirectory.get');

    expect(result).toMatchObject({success: false, error: {code: 'RequestTimeout'}});
  });

  it("honours a caller's own abort signal", async () => {
    const controller = new AbortController();
    // Modelled on the real thing: `fetch` rejects IMMEDIATELY for a signal that is already
    // aborted, and only listens otherwise. A mock that merely listened would hang here — which
    // is a window the client has to handle, for a signal aborted before the request starts.
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      const abortError = () => Object.assign(new Error('aborted'), {name: 'AbortError'});
      if (init.signal?.aborted) return Promise.reject(abortError());
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(abortError()));
      });
    });

    const pending = apiRequest('userDirectory.get', {signal: controller.signal});
    controller.abort();

    await expect(pending).resolves.toMatchObject({success: false, error: {code: 'RequestTimeout'}});
  });
});

describe('apiRequest — path parameters', () => {
  it('fills the template from the route id, so no caller assembles a URL', async () => {
    fetchMock.mockResolvedValue(json(200, {}));

    await apiRequest('athena.stop', {params: {queryExecutionId: 'abc-123'}});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/queries/abc-123/stop`);
  });

  it('encodes each segment, because the gateway hands the server a DECODED path', async () => {
    // Measured against the deployed API, not assumed: `GET /health%7A` answered 200 having
    // matched `/healthz`, and `/healthz%20` answered 401. So this is the one encode point and
    // the server never unquotes.
    fetchMock.mockResolvedValue(json(200, {}));

    await apiRequest('athena.stop', {params: {queryExecutionId: 'a b%c'}});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/queries/a%20b%25c/stop`);
  });

  it.each([
    ['a slash the gateway decodes back into a separator', 'abc/results'],
    ['a dot segment the URL parser collapses before the wire', '.'],
    ['a parent segment the URL parser collapses before the wire', '..'],
    ['an empty value, which would make an empty segment', '']
  ])('refuses %s rather than sending it', async (_why, value) => {
    // All four address a template the caller did not name, by two different mechanisms at two
    // different layers: `a/b` survives encoding and is decoded by API Gateway, while `.` is not
    // encoded at all and never reaches the wire — `fetch`'s URL parser collapses it. So the rule
    // is "one path segment", not "no slash"; a slash-only check passes `.` and lands the caller
    // on `athena.results` with a 200 and a body of the wrong shape.
    const result = await apiRequest('athena.status', {params: {queryExecutionId: value}});

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toMatchObject({success: false, error: {code: 'UnsendableParameter'}});
  });

  it('returns a failure rather than throwing when a value is not a string at runtime', async () => {
    // The types forbid it and a cast reinstates it — `options.params` is read through one. This
    // module's contract is that it never throws, and `value.includes` on `undefined` does.
    const params = {queryExecutionId: undefined} as unknown as {queryExecutionId: string};

    const result = await apiRequest('athena.status', {params});

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result).toMatchObject({success: false, error: {code: 'UnsendableParameter'}});
  });

  it('will not compile a templated route with no parameters', async () => {
    fetchMock.mockResolvedValue(json(200, {}));

    // @ts-expect-error a templated route makes the options object and its `params` REQUIRED. As
    // an optional field this compiled, and the literal `/v1/queries/{queryExecutionId}/stop` went
    // on the wire — where the gateway decodes the braces and the server's matcher MATCHES, so
    // Athena would receive `{queryExecutionId}` as an execution id and answer a 400 about a value
    // nobody typed. The assertion IS the `@ts-expect-error`: weaken the type and `tsc -b` fails
    // here for having nothing to suppress.
    await apiRequest('athena.stop');
  });

  it('round-trips a continuation token through the query string byte for byte', async () => {
    // The browser half of a round trip whose server half was already asserted — and whose test
    // said in its own docstring that this half existed. It did not. Athena's and S3's tokens are
    // base64 and routinely carry all three of these; unencoded, `+` decodes to a space and the
    // next page silently restarts from the beginning rather than erroring.
    fetchMock.mockResolvedValue(json(200, {columns: [], rows: [], nextToken: null}));
    const awkward = 'a+b/c==';

    await apiRequest('athena.results', {
      params: {queryExecutionId: 'abc-123'},
      query: {nextToken: awkward}
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = new URL(fetchMock.mock.calls[0][0], window.location.origin);
    expect(url.searchParams.get('nextToken')).toBe(awkward);
    expect(url.search).toContain('a%2Bb%2Fc%3D%3D');
  });
});
