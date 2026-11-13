import {describe, expect, it} from 'vitest';
import {LOCKDOWN_POLICY, SECURITY_HEADERS} from '../lib/securityHeaders';
import {contentSecurityPolicy, newNonce} from './contentSecurityPolicy';

/**
 * The policy as Terraform assembled it before the Next.js server took it over, recorded as a
 * literal, with the separator it was joined on.
 *
 * Recorded rather than re-derived from the module: a CSP is observed by nothing offline, and an
 * expectation built from the code under test would only assert that the file equals itself.
 * `script-src` is the one directive the move changes, because the policy now carries a nonce; it is
 * asserted on its own below. A deliberate policy change edits this list in the same commit.
 */
const RECORDED_DIRECTIVES = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data:",
  "font-src 'self' data: https://fonts.gstatic.com",
  "worker-src 'self' blob:",
  'connect-src ${PORTAL_CSP_CONNECT_SRC}',
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  'upgrade-insecure-requests'
];
const RECORDED_SEPARATOR = '; ';

const CONNECT = "'self' https://api.portal.test";

describe('the page policy', () => {
  it('is the recorded policy, directive by directive, with a nonce in script-src alone', () => {
    const policy = contentSecurityPolicy({nonce: 'TONCE', connectSrc: CONNECT, development: false});

    // Split on the separator and compared in order: joined on anything else, the browser reads one
    // malformed directive and drops every other, which an element-only comparison cannot see.
    const directives = policy.split(RECORDED_SEPARATOR);
    expect(directives).toEqual(
      RECORDED_DIRECTIVES.map((directive) =>
        directive === "script-src 'self'"
          ? "script-src 'self' 'nonce-TONCE'"
          : directive.replace('${PORTAL_CSP_CONNECT_SRC}', CONNECT)
      )
    );
    // Only script-src carries it: a nonce in style-src switches off the 'unsafe-inline' Monaco's
    // injected styles need.
    expect(directives.filter((directive) => directive.includes('nonce-'))).toEqual(["script-src 'self' 'nonce-TONCE'"]);
  });

  it("adds 'unsafe-eval' under next dev and never otherwise", () => {
    const development = contentSecurityPolicy({nonce: 'N', connectSrc: CONNECT, development: true});
    const production = contentSecurityPolicy({nonce: 'N', connectSrc: CONNECT, development: false});

    expect(development).toContain("script-src 'self' 'nonce-N' 'unsafe-eval';");
    expect(production).not.toContain('unsafe-eval');
  });

  it('mints a fresh 16-byte nonce each time', () => {
    const first = newNonce();
    const second = newNonce();

    expect(first).not.toBe(second);
    expect(atob(first)).toHaveLength(16);
  });
});

describe('the headers every response carries', () => {
  it('are the seven, with HSTS carrying no preload and no COEP among them', () => {
    expect(Object.keys(SECURITY_HEADERS).sort()).toEqual(
      [
        'Cross-Origin-Opener-Policy',
        'Cross-Origin-Resource-Policy',
        'Permissions-Policy',
        'Referrer-Policy',
        'Strict-Transport-Security',
        'X-Content-Type-Options',
        'X-Frame-Options'
      ].sort()
    );
    expect(SECURITY_HEADERS['Strict-Transport-Security']).toBe('max-age=31536000; includeSubDomains');
  });

  it('give a request with a body a policy that runs nothing', () => {
    expect(LOCKDOWN_POLICY.split('; ')).toEqual([
      "default-src 'none'",
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors 'none'"
    ]);
  });
});
