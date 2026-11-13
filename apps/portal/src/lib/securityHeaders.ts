/**
 * The response headers every portal response carries, other than its Content-Security-Policy.
 *
 * Shared by the request proxy and `next.config.ts`, which is why this module imports no
 * `server-only`: the config runs in plain Node, where that package's import fails the build. It
 * holds policy text and nothing secret, and nothing in the browser bundle imports it.
 *
 * Deliberately absent: `Cross-Origin-Embedder-Policy`. `require-corp` buys cross-origin isolation
 * this app has no use for (no SharedArrayBuffer, no high-resolution timers) at a real risk to
 * subresource loads, and the scanner alert it would clear is accepted in the security baseline.
 *
 * HSTS carries no `preload`. That claims a submission to the preload list this deployment has not
 * made and does not intend, and the grant is against the registrable domain, which this
 * repository does not own.
 */
export const SECURITY_HEADERS: Readonly<Record<string, string>> = Object.freeze({
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
  'X-Frame-Options': 'DENY',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy':
    'accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Resource-Policy': 'same-origin'
});

/**
 * The policy for a response to a request that carried a body.
 *
 * No page takes a body, so a response to one has no business running script, loading a frame or
 * submitting a form. Such a request skips the proxy, so this is all the policy it gets.
 */
export const LOCKDOWN_POLICY = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
