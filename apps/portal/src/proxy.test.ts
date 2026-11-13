import {NextRequest} from 'next/server';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {SECURITY_HEADERS} from './lib/securityHeaders';
import {config, proxy} from './proxy';

/**
 * The headers Next forwards to the page are read from the response's override headers: that is
 * how `NextResponse.next({request: {headers}})` hands them on.
 */
function forwarded(response: Response, name: string): string | null {
  return response.headers.get(`x-middleware-request-${name}`);
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('the request proxy', () => {
  it('sends one fresh nonce to the page and the same nonce in the response policy', () => {
    vi.stubEnv('PORTAL_CSP_CONNECT_SRC', "'self' https://api.portal.test");
    const request = new NextRequest('https://portal.test/files', {
      headers: {'x-nonce': 'chosen-by-the-client', 'content-security-policy': 'script-src *'}
    });

    const first = proxy(request);
    const second = proxy(new NextRequest('https://portal.test/files'));

    const nonce = forwarded(first, 'x-nonce');
    expect(nonce).not.toBe('chosen-by-the-client');
    expect(nonce).not.toBe(forwarded(second, 'x-nonce'));
    const policy = first.headers.get('content-security-policy');
    expect(policy).toContain(`script-src 'self' 'nonce-${nonce}';`);
    expect(forwarded(first, 'content-security-policy')).toBe(policy);
    expect(policy).toContain("connect-src 'self' https://api.portal.test;");
  });

  it('sets every security header and no Cache-Control', () => {
    const response = proxy(new NextRequest('https://portal.test/'));

    for (const [name, value] of Object.entries(SECURITY_HEADERS)) expect(response.headers.get(name), name).toBe(value);
    // A Cache-Control set here would override a route handler's no-store and Next's immutable.
    expect(response.headers.get('cache-control')).toBeNull();
  });

  it('matches only requests that carry no body', () => {
    // A request with a body that reaches the proxy is held until the whole body arrives.
    expect(config.matcher).toEqual([
      {
        source: '/:path*',
        missing: [
          {type: 'header', key: 'content-length'},
          {type: 'header', key: 'transfer-encoding'}
        ]
      }
    ]);
  });
});
