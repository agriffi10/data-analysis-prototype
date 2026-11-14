/**
 * How a path selects an App Router page file, by Next's rules for the segment kinds this app uses:
 * a static segment before a dynamic one (`[x]`) before a catch-all (`[...x]`) before an optional
 * catch-all (`[[...x]]`), and a route group (`(x)`) adds nothing to the address. Pure, so the rules
 * are proved against fixture file maps whatever is on disk; `renderApp` and the record-and-page
 * guard share it.
 *
 * File paths are relative to `src/app/`, as `(signed-in)/files/page.tsx`.
 */

type Segment =
  | {kind: 'static'; value: string}
  | {kind: 'dynamic'; name: string}
  | {kind: 'catch-all'; name: string}
  | {kind: 'optional-catch-all'; name: string};

/** Lower ranks win, compared segment by segment. */
const RANK: Record<Segment['kind'], number> = {static: 0, dynamic: 1, 'catch-all': 2, 'optional-catch-all': 3};

/** A page's params as Next hands them over: percent-encoded, a catch-all's as its segments. */
export type PageParams = Record<string, string | string[]>;

/**
 * A page file's segments, route groups and the file name dropped.
 *
 * @param file - The file's path under `src/app/`.
 * @returns Its segments in order.
 */
export function segmentsOf(file: string): Segment[] {
  const parts = file.split('/');
  if (parts.at(-1) !== 'page.tsx') throw new Error(`${file} is not a page file`);
  return parts
    .slice(0, -1)
    .filter((part) => !(part.startsWith('(') && part.endsWith(')')))
    .map((part): Segment => {
      let match = /^\[\[\.\.\.(\w+)\]\]$/.exec(part);
      if (match) return {kind: 'optional-catch-all', name: match[1]};
      match = /^\[\.\.\.(\w+)\]$/.exec(part);
      if (match) return {kind: 'catch-all', name: match[1]};
      match = /^\[(\w+)\]$/.exec(part);
      if (match) return {kind: 'dynamic', name: match[1]};
      return {kind: 'static', value: part};
    });
}

/**
 * The route pattern a page file serves, as the area records spell one (`/data-quality/:space/:requestId`),
 * or null for a catch-all, which no record names.
 *
 * @param file - The file's path under `src/app/`.
 * @returns The pattern, or null.
 */
export function patternOf(file: string): string | null {
  const segments = segmentsOf(file);
  if (segments.some((segment) => segment.kind === 'catch-all' || segment.kind === 'optional-catch-all')) return null;
  return `/${segments.map((segment) => (segment.kind === 'static' ? segment.value : `:${'name' in segment ? segment.name : ''}`)).join('/')}`;
}

/**
 * Whether a page file serves a path, and with what params.
 *
 * @param file - The file's path under `src/app/`.
 * @param pathname - The path, percent-encoded as in the address.
 * @returns The params, or null when it does not match.
 */
export function matchPage(file: string, pathname: string): PageParams | null {
  const parts = pathname.split('/').filter(Boolean);
  const params: PageParams = {};
  const segments = segmentsOf(file);
  for (const [index, segment] of segments.entries()) {
    const part = parts[index];
    if (segment.kind === 'optional-catch-all' || segment.kind === 'catch-all') {
      const rest = parts.slice(index);
      if (segment.kind === 'catch-all' && rest.length === 0) return null;
      if (rest.length > 0) params[segment.name] = rest;
      return params;
    }
    if (part === undefined) return null;
    if (segment.kind === 'static' && segment.value !== part) return null;
    if (segment.kind === 'dynamic') params[segment.name] = part;
  }
  return parts.length === segments.length ? params : null;
}

/** Negative when `a` is the more specific file, by Next's precedence. */
function compareSpecificity(a: string, b: string): number {
  const left = segmentsOf(a);
  const right = segmentsOf(b);
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const l = left[index];
    const r = right[index];
    if (!l || !r) return l ? -1 : 1;
    if (RANK[l.kind] !== RANK[r.kind]) return RANK[l.kind] - RANK[r.kind];
  }
  return 0;
}

/**
 * The page file Next would render for a path, and its params.
 *
 * @param files - Every page file, by its path under `src/app/`.
 * @param pathname - The path, percent-encoded as in the address.
 * @returns The selected file and its params, or null when none serves the path.
 */
export function selectPage(files: readonly string[], pathname: string): {file: string; params: PageParams} | null {
  const matching = files
    .map((file) => ({file, params: matchPage(file, pathname)}))
    .filter((candidate): candidate is {file: string; params: PageParams} => candidate.params !== null)
    .sort((a, b) => compareSpecificity(a.file, b.file));
  return matching[0] ?? null;
}
