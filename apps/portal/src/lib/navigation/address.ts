import type {To} from './navigation.types';

/** A path, its query and its hash: an address without the state a navigation carried. */
export type Address = {pathname: string; search: string; hash: string};

/** The field the seam writes its key into, beside Next's own state on the history entry. */
export const KEY_FIELD = '__seamKey';

/** A base that is never fetched, for parsing a path on its own. */
const PARSE_BASE = 'https://portal.invalid';

/**
 * A query string as `URLSearchParams` serializes it, for comparing two addresses.
 *
 * Next's `useSearchParams` re-serializes the search (`%20` comes back as `+`), so two spellings of
 * one address compare equal only once both are parsed. The seam's location keeps the raw form,
 * because `useRefreshLink` reads names percent-encoded around a literal comma, and a re-serialized
 * search encodes that comma too.
 *
 * @param search - A query string, with or without its `?`.
 * @returns The canonical form, `''` when empty.
 */
export function normalizeSearch(search: string): string {
  const serialized = new URLSearchParams(search).toString();
  return serialized ? `?${serialized}` : '';
}

/**
 * A path as the browser writes it into the address (spaces and other reserved characters
 * percent-encoded, dot segments resolved), so a target compares equal to what Next reports.
 *
 * @param pathname - An absolute path.
 * @returns The path the address bar would show.
 */
export function normalizePathname(pathname: string): string {
  return new URL(pathname, PARSE_BASE).pathname;
}

/**
 * Whether two addresses name the same document: the same path and the same query, the hash
 * aside, each compared in its canonical form.
 */
export function sameDocument(a: Address, b: Address): boolean {
  return (
    normalizePathname(a.pathname) === normalizePathname(b.pathname) &&
    normalizeSearch(a.search) === normalizeSearch(b.search)
  );
}

/** The address as one string, as written into the history entry. */
export function hrefOf(address: Address): string {
  return address.pathname + address.search + address.hash;
}

/** The committed address: what the browser shows, never the seam's latest render. */
export function committedAddress(): Address {
  return {pathname: window.location.pathname, search: window.location.search, hash: window.location.hash};
}

/** A `To` as one string, for the origin check and for an anchor's `href`. */
export function toHref(to: To): string {
  return typeof to === 'string' ? to : `${to.pathname ?? ''}${to.search ?? ''}${to.hash ?? ''}`;
}

/**
 * Whether a target leaves the portal's own origin.
 *
 * Parsed against the current address, the check `notificationLink.ts` uses: it catches every form
 * that leaves the site (`//host`, `/\host`, `\\host`, a leading space or tab, `https:host`, an
 * absolute URL), and `javascript:` and `data:` through their null origin. An unparseable target is
 * refused too.
 *
 * @param href - The target as one string.
 * @returns True when the target is not the portal's own.
 */
export function isOffSite(href: string): boolean {
  try {
    return new URL(href, window.location.href).origin !== window.location.origin;
  } catch {
    return true;
  }
}

/**
 * Whether the seam refuses a target: when it leaves the portal as written, or once resolved.
 *
 * Both, because they can differ: a dot segment before a doubled slash (`/.//host/x`) is a path as
 * written, and resolves through the URL parser to a protocol-relative `//host/x`. The resolution
 * collapses doubled slashes as react-router's does, so such a target stays in the portal, and the
 * check on the resolved address is what holds if it ever does not.
 *
 * @param to - The target.
 * @param from - The address it is resolved against.
 * @returns True when the target is not the portal's own.
 */
export function isRefusedTarget(to: To, from: Address): boolean {
  return isOffSite(toHref(to)) || isOffSite(hrefOf(resolveTo(to, from)));
}

/**
 * A path as react-router matches it: each segment decoded, an encoded slash kept encoded, so the
 * gate claims exactly the paths the route table serves (`/fil%65s` is Files to both).
 *
 * @param pathname - A path, percent-encoded as in the address.
 * @returns The decoded path.
 */
export function decodePath(pathname: string): string {
  return pathname
    .split('/')
    .map((segment) => {
      try {
        return decodeURIComponent(segment).replace(/\//g, '%2F');
      } catch {
        return segment;
      }
    })
    .join('/');
}

/** What the URL parser strips from a target before reading it: outer C0 controls and spaces, inner tabs and newlines. */
function stripLikeTheParser(to: string): string {
  // eslint-disable-next-line no-control-regex -- the URL parser strips exactly these, so the seam does too.
  return to.replace(/^[\u0000- ]+|[\u0000- ]+$/g, '').replace(/[\t\n\r]/g, '');
}

/**
 * Resolves a `To` against an address the way react-router resolves one against a location, so
 * nothing changes for a caller: a hash-only target keeps the path and drops the query, a
 * query-only one keeps the path and drops the hash, an absolute path replaces the path, and a
 * relative one resolves beneath the current path, doubled slashes collapsing. The path comes back as
 * the address bar spells it.
 *
 * @param to - The target.
 * @param from - The address it is resolved against.
 * @returns The address to navigate to, its query raw.
 */
export function resolveTo(to: To, from: Address): Address {
  let parts: Address;
  if (typeof to === 'string') {
    const target = stripLikeTheParser(to);
    const hashAt = target.indexOf('#');
    const beforeHash = hashAt < 0 ? target : target.slice(0, hashAt);
    const queryAt = beforeHash.indexOf('?');
    parts = {
      pathname: queryAt < 0 ? beforeHash : beforeHash.slice(0, queryAt),
      search: queryAt < 0 ? '' : beforeHash.slice(queryAt),
      hash: hashAt < 0 ? '' : target.slice(hashAt)
    };
  } else {
    parts = {pathname: to.pathname ?? '', search: to.search ?? '', hash: to.hash ?? ''};
  }
  // Doubled slashes collapse, as react-router's resolution collapses them.
  parts.pathname = parts.pathname.replace(/[/\\]{2,}/g, '/');
  const pathname = !parts.pathname
    ? from.pathname
    : /^[/\\]/.test(parts.pathname)
      ? normalizePathname(parts.pathname)
      : new URL(parts.pathname, `${PARSE_BASE}${from.pathname.endsWith('/') ? from.pathname : `${from.pathname}/`}`)
          .pathname;
  return {
    // A trailing slash goes, as Next's router and server both drop it.
    pathname: pathname.length > 1 ? pathname.replace(/\/+$/, '') || '/' : pathname,
    search: parts.search === '?' ? '' : parts.search,
    hash: parts.hash === '#' ? '' : parts.hash
  };
}

/** The seam's key on a history entry's state, or `'default'` for an entry with none, as an in-page anchor's. */
export function keyOf(state: unknown): string {
  const key = (state as Record<string, unknown> | null | undefined)?.[KEY_FIELD];
  return typeof key === 'string' ? key : 'default';
}

/** A fresh key for a push or a replace, in react-router's shape. */
export function newKey(): string {
  return Math.random().toString(36).slice(2, 10);
}
