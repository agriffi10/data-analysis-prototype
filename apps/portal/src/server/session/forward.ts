import 'server-only';
import {refusal} from './refusal';
import {deadline} from './deadline';

/** The HTTP API's own payload quota. A larger body would be refused there anyway. */
export const MAX_BODY_BYTES = 10 * 1024 * 1024;

/** Past the API Gateway integration's 30 seconds, so the API's own timeout arrives first. */
export const FORWARD_TIMEOUT_MS = 35_000;

/** What reaches the API from the browser's request, besides the bearer the server attaches. */
const REQUEST_HEADERS = ['content-type', 'accept', 'x-request-id'] as const;

/** What reaches the browser from the API's response: the headers the API sets. */
const RESPONSE_HEADERS = ['content-type', 'cache-control', 'www-authenticate'] as const;

/**
 * The API URL a request to `/api/<rest>` is forwarded to.
 *
 * Built by concatenation and then checked to have the API's origin. `new URL(rest, apiOrigin)` would
 * resolve `//evil.example/x` to another host and hand it the session's token.
 *
 * @param apiOrigin - The API's origin, from configuration.
 * @param requestUrl - The incoming request's URL.
 * @returns The target, or undefined when the path is not under `/api/` or would leave the API.
 */
export function apiTarget(apiOrigin: string, requestUrl: string): string | undefined {
  const incoming = new URL(requestUrl);
  if (!incoming.pathname.startsWith('/api/')) return undefined;
  const rest = incoming.pathname.slice('/api/'.length);
  if (rest === '') return undefined;
  const target = `${apiOrigin}/${rest}${incoming.search}`;
  try {
    return new URL(target).origin === new URL(apiOrigin).origin ? target : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Whether a request declares a body larger than the API will take, read from the header alone.
 *
 * @param request - The incoming request.
 * @returns True when `content-length` names more than the cap.
 */
export function declaresTooMuch(request: Request): boolean {
  const declared = request.headers.get('content-length');
  return declared !== null && Number(declared) > MAX_BODY_BYTES;
}

/**
 * Read a request's body, stopping as soon as it passes the cap, whatever it declared.
 *
 * @param request - The incoming request.
 * @returns The body, or `too-large`.
 */
export async function readBoundedBody(request: Request): Promise<Uint8Array<ArrayBuffer> | 'too-large'> {
  if (!request.body) return new Uint8Array(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY_BYTES) {
      await reader.cancel();
      return 'too-large';
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

/**
 * Forward one request to the API with the session's ID token, and return the API's answer.
 *
 * Redirects are not followed: a followed cross-origin redirect drops the bearer but re-sends the
 * body to the other host and hands its answer to the browser. The API answers none, so any 3xx is a
 * fault. A 401 from the API passes through unchanged.
 *
 * @param request - The incoming request.
 * @param target - The API URL, from `apiTarget`.
 * @param idToken - The session's ID token.
 * @param body - The request's body, already bounded, or undefined for none.
 * @returns The API's response, with only its own headers.
 */
export async function forward(
  request: Request,
  target: string,
  idToken: string,
  body: Uint8Array<ArrayBuffer> | undefined
): Promise<Response> {
  const headers = new Headers({authorization: `Bearer ${idToken}`});
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  const requestId = request.headers.get('x-request-id') ?? undefined;

  const bound = deadline(FORWARD_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers,
      body: body && body.byteLength > 0 ? body : undefined,
      redirect: 'manual',
      signal: bound.signal
    });
  } catch {
    console.error('session: the API did not answer a forwarded request');
    return refusal('ApiUnavailable', requestId);
  } finally {
    bound.clear();
  }
  if (response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
    console.error('session: the API answered a forwarded request with a redirect');
    return refusal('ApiUnavailable', requestId);
  }

  const passed = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = response.headers.get(name);
    if (value !== null) passed.set(name, value);
  }
  return new Response(request.method === 'HEAD' ? null : response.body, {status: response.status, headers: passed});
}
