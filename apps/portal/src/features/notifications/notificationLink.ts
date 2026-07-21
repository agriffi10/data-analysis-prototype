/**
 * Is `link` a safe IN-APP path that may be rendered as a router `<Link>`?
 *
 * A notification's `link` is written by a Lambda control plane and read back out of
 * S3, so it is data from outside the SPA — and it becomes an anchor the user is
 * invited to click. Anything that could resolve OFF this origin is an open redirect
 * wearing the app's own chrome, which is why this defaults to rejecting.
 *
 * Accepted: a single-slash absolute path (`/data-quality/alice/req-1`).
 *
 * Rejected, and each for a reason worth naming:
 *  - `https://evil.test` and any other scheme, including `javascript:` — not a path.
 *  - `//evil.test` — PROTOCOL-RELATIVE. It looks like a path and is not one; the
 *    browser resolves it to another origin entirely.
 *  - `/\evil.test` and `/\\evil.test` — the same attack past a naive `//` check:
 *    browsers normalize a backslash to a forward slash in the authority position.
 *  - a relative path (`data-quality/...`) — resolves against whatever route the user
 *    happens to be on, so where it lands is not knowable here.
 *
 * The caller renders plain text when this returns false, so a rejected link degrades
 * to exactly the notification a producer that supplied no link would have produced.
 */
export function isSafeInAppPath(link: unknown): link is string {
  if (typeof link !== 'string' || link.length < 1) return false;
  if (link[0] !== '/') return false;
  // Second character decides: anything that can open an authority is out.
  return link[1] !== '/' && link[1] !== '\\';
}
