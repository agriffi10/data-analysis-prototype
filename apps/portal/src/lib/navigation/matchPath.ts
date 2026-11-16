/**
 * Whether `pathname` matches a route pattern, and with what params.
 *
 * Matched as the matcher this one replaced matched, so no caller's match changed: the pattern's
 * leading slashes count as one and its trailing ones as none, a static segment matches itself
 * exactly and case-sensitively, as Next routes (`/Files` is no area), a `:name` parameter matches a
 * whole non-empty segment, a whole match allows trailing slashes, and a prefix match (`end: false`)
 * ends at a segment boundary. It decodes nothing: a parameter comes back as it stands in `pathname`,
 * except that `%2F` becomes `/`, so a caller that wants decoded params hands it the path `decodePath`
 * has decoded segment by segment, which keeps an encoded slash as `%2F`.
 *
 * @param pattern - A route pattern (`/data-quality/:space/:requestId`), or one with `end: false` to
 *   match a prefix at a segment boundary.
 * @param pathname - The path to test.
 * @returns The params, or null when it does not match.
 * @throws Error for a splat or an optional segment, which no caller uses and this matcher does not model.
 *
 * @example
 * matchPath('/files', '/Files'); // null
 */
export function matchPath(
  pattern: string | {path: string; end?: boolean},
  pathname: string
): {params: Record<string, string | undefined>} | null {
  const {path, end = true} = typeof pattern === 'string' ? {path: pattern} : pattern;
  if (/[*?]/.test(path)) throw new Error(`matchPath does not model the pattern ${path}`);
  const segments = path.replace(/\/+$/, '').replace(/^\/+/, '').split('/');
  if (segments.length === 1 && segments[0] === '') segments.pop();
  if (!pathname.startsWith('/')) return null;

  const params: Record<string, string | undefined> = {};
  let at = 1;
  for (const [index, segment] of segments.entries()) {
    if (index > 0) {
      if (pathname[at] !== '/') return null;
      at += 1;
    }
    if (segment.startsWith(':')) {
      const close = pathname.indexOf('/', at);
      const value = pathname.slice(at, close < 0 ? pathname.length : close);
      if (!value) return null;
      params[segment.slice(1)] = value.replace(/%2F/g, '/');
      at += value.length;
    } else {
      if (!pathname.startsWith(segment, at)) return null;
      at += segment.length;
    }
  }

  const rest = pathname.slice(at);
  if (end) return /^\/*$/.test(rest) ? {params} : null;
  return segments.length === 0 || rest === '' || rest.startsWith('/') ? {params} : null;
}
