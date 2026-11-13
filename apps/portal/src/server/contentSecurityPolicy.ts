import 'server-only';

/**
 * The page policy's directives, in order, with `script-src` and `connect-src` built per request.
 *
 * Every other directive describes the bundle: what it may style, fetch a font from, spawn a worker
 * as. `style-src` keeps `'unsafe-inline'` because Monaco injects `<style>` elements at runtime, and
 * it carries no nonce because a nonce in a directive switches that allowance off. The Google
 * stylesheet is `index.css`'s first `@import`, which the build leaves in place, and it serves its
 * font files from gstatic.
 */
const BUNDLE_DIRECTIVES_BEFORE_CONNECT = [
  "default-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data:",
  "font-src 'self' data: https://fonts.gstatic.com",
  "worker-src 'self' blob:"
] as const;

const BUNDLE_DIRECTIVES_AFTER_CONNECT = [
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  'upgrade-insecure-requests'
] as const;

/**
 * A fresh nonce for one response: 16 cryptographically random bytes, base64-encoded.
 *
 * @returns The nonce, never reused across requests.
 */
export function newNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

/**
 * The enforcing Content-Security-Policy for one page response.
 *
 * Scripts run only from this origin or with this response's nonce, which Next stamps on every
 * script and stylesheet it emits and the root layout puts on `theme-init.js`. `'unsafe-eval'` is
 * added in development only, because React's development build evaluates code to rebuild server
 * error stacks; production evaluates nothing.
 *
 * @param options.nonce - This response's nonce.
 * @param options.connectSrc - The source list the task definition supplies; the environment's one
 *   directive, already validated at server start.
 * @param options.development - Whether the server runs `next dev`.
 * @returns The policy, its directives joined by `"; "`.
 */
export function contentSecurityPolicy(options: {nonce: string; connectSrc: string; development: boolean}): string {
  const scriptSrc = `script-src 'self' 'nonce-${options.nonce}'${options.development ? " 'unsafe-eval'" : ''}`;
  const [defaultSrc, ...rest] = BUNDLE_DIRECTIVES_BEFORE_CONNECT;
  return [defaultSrc, scriptSrc, ...rest, `connect-src ${options.connectSrc}`, ...BUNDLE_DIRECTIVES_AFTER_CONNECT].join(
    '; '
  );
}
