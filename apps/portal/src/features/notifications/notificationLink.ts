import {spaceBuckets} from '../../lib/userSpace';

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

/**
 * The href of a notification's own action control: where the row already points, plus the
 * request the notification is about.
 *
 * Built with `URLSearchParams` rather than by choosing a separator, because the base may
 * already carry a query — `/files?space=finance&prefix=…` is the ordinary case — and a
 * hand-rolled `?` produces a URL that no gate has seen. The id is encoded on the way in.
 *
 * `base` is whatever the row resolved as safe and ungated, and `/files` is the fallback: the
 * action must stay reachable for someone whose notification carries no usable prefix, because
 * the alternative is a user who closed the submitting tab having nowhere to go at all.
 */
export function reviewHref(base: string | undefined, requestId: string): string {
  const [path, query] = (base ?? '/files').split('?');
  const params = new URLSearchParams(query);
  params.set('requestId', requestId);
  return `${path}?${params.toString()}`;
}

/**
 * The bucket and folder a `/files` notification link resolves to, or undefined for any other link.
 *
 * A link carries a space NAME and a prefix; the file browser's cache is keyed by BUCKET and
 * prefix, and the two buckets are runtime config. So following a link cannot refresh the folder
 * it lands on without this translation — the notification has no bucket in it and never will,
 * because a bucket name is deployment detail a control plane has no business minting into a URL.
 *
 * The presence of `space` is what decides which bucket: the link producer writes it only for a
 * shared destination.
 *
 * Returns undefined rather than guessing when the link is not a `/files` one, carries no usable
 * prefix, or names a bucket this deployment has not configured — each of which is a reason to
 * navigate without refreshing rather than to refresh the wrong folder.
 *
 * @param link - A link already accepted by `isSafeInAppPath`.
 * @returns The listing to invalidate, or undefined.
 */
export function filesLinkListing(link: string): {bucket: string; prefix: string} | undefined {
  const [path, query] = link.split('?');
  if (path !== '/files' || !query) return undefined;
  const params = new URLSearchParams(query);
  const prefix = params.get('prefix');
  if (!prefix) return undefined;
  const {user, shared} = spaceBuckets();
  const bucket = params.has('space') ? shared : user;
  return bucket ? {bucket, prefix} : undefined;
}
