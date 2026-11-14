import {matchPath as matchRoute} from 'react-router';

/**
 * Whether `pathname` matches a route pattern, and with what params.
 *
 * Case-sensitive, as Next routes: `/Files` is no area under either router. react-router's matcher
 * folds case by default, so a moved area would have rendered a 404 inside the shell at `/Files`
 * while the gate still called it signed in. react-router does the matching here until the last of
 * it retires; nothing outside the seam reaches it.
 *
 * @param pattern - A route pattern (`/data-quality/:space/:requestId`), or one with `end: false` to
 *   match a prefix at a segment boundary.
 * @param pathname - The path to test.
 * @returns The decoded params, or null when it does not match.
 *
 * @example
 * matchPath('/files', '/Files'); // null
 */
export function matchPath(
  pattern: string | {path: string; end?: boolean},
  pathname: string
): {params: Record<string, string | undefined>} | null {
  const {path, end = true} = typeof pattern === 'string' ? {path: pattern} : pattern;
  const match = matchRoute({path, caseSensitive: true, end}, pathname);
  return match ? {params: {...match.params}} : null;
}
