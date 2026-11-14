import 'server-only';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/**
 * Whether a request may change something without first passing the `Origin` check.
 *
 * @param method - The request's method.
 * @returns True for GET, HEAD and OPTIONS.
 */
export function isSafeMethod(method: string): boolean {
  return SAFE_METHODS.has(method.toUpperCase());
}

/**
 * Whether an unsafe request came from the portal's own pages.
 *
 * `SameSite=Lax` does not stop a request from a sibling subdomain such as the API's, so the session
 * cookie needs this. A missing `Origin` is refused too: browsers send it on every cross-origin
 * request and on every same-origin one that is not GET or HEAD, so its absence is not a browser.
 * The comparison is exact, against configuration, never against the request's own `Host`.
 *
 * @param request - The request.
 * @param portalOrigin - The portal's origin, from configuration.
 * @returns True when `Origin` is exactly the portal's.
 */
export function fromThePortal(request: Request, portalOrigin: string): boolean {
  return request.headers.get('origin') === portalOrigin;
}
