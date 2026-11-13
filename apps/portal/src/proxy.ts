import {NextResponse, type NextRequest} from 'next/server';
import {SECURITY_HEADERS} from './lib/securityHeaders';
import {contentSecurityPolicy, newNonce} from './server/contentSecurityPolicy';
import {connectSource} from './server/runtimeDocument';

/**
 * Stamp one request with a fresh nonce, and its response with the policy and security headers.
 *
 * The nonce and the policy go on the REQUEST as well as the response: Next reads the policy from
 * the request to stamp the nonce on every script and stylesheet it emits, and the root layout reads
 * `x-nonce` for `theme-init.js`. Setting both overwrites anything the client sent under those names.
 *
 * It sets no `Cache-Control`. A header set here overrides every other source, including a route
 * handler's `no-store` and Next's `immutable` on hashed assets (measured), so each cache class is
 * left to its owner.
 *
 * @param request - The incoming request, which carries no body (see `config`).
 * @returns The request passed on, with the headers set.
 */
export function proxy(request: NextRequest): NextResponse {
  const nonce = newNonce();
  const policy = contentSecurityPolicy({
    nonce,
    connectSrc: connectSource(),
    development: process.env.NODE_ENV === 'development'
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', policy);

  const response = NextResponse.next({request: {headers: requestHeaders}});
  response.headers.set('Content-Security-Policy', policy);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) response.headers.set(name, value);
  return response;
}

/**
 * Every path, but only requests that carry no body.
 *
 * When the proxy matches a request with a body, Next clones the body for it and then waits for the
 * WHOLE body before any page or handler answers, whatever the proxy returns. A client declaring a
 * gigabyte and sending one byte held every path, the health probe included (measured). No page
 * takes a body, so such a request skips the proxy, and `next.config.ts` gives exactly those
 * requests the security headers and a policy that runs nothing.
 */
export const config = {
  matcher: [
    {
      source: '/:path*',
      missing: [
        {type: 'header', key: 'content-length'},
        {type: 'header', key: 'transfer-encoding'}
      ]
    }
  ]
};
