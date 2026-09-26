import {matchPath} from 'react-router';
import {NAV_PATH_FLAGS} from './gatedSurfaces';
import type {FeatureFlagKey} from './featureFlags.types';

/**
 * How one route names a space in its URL, and how it spells the viewer's personal one.
 *
 * Each route answers both questions its own way — `/files` takes a connection id, the report
 * route a username — so a single rule would be right for one of them and quietly wrong for the
 * others. Each row mirrors the reader that route already uses.
 */
type SpaceReader = {
  /** The route pattern, as `matchPath` reads it. */
  pattern: string;
  /** The space the URL names, or null when it names none. */
  read: (url: URL, params: Record<string, string | undefined>) => string | null;
  /** Whether that name is the viewer's personal space in this route's spelling. */
  isPersonal: (name: string, username: string | null) => boolean;
};

/** Every in-app route whose URL can name a space. */
const SPACE_READERS: readonly SpaceReader[] = [
  // `useFileSpace`: `?space=` is a connection id, and the personal connection's id is the literal.
  {pattern: '/files', read: (url) => url.searchParams.get('space'), isPersonal: (name) => name === 'personal'},
  // `exploreSources.resolveSpace`: the literal OR the username, because the Query rail hands over
  // a database name and the personal database is named for its owner.
  {
    pattern: '/explore',
    read: (url) => url.searchParams.get('space'),
    isPersonal: (name, username) => name === 'personal' || name === username
  },
  // `parseRefreshLink`: `?refreshTable=<database>.<table>`, where a shared space's database is its
  // name and the personal database is the username.
  {
    pattern: '/query',
    read: (url) => url.searchParams.get('refreshTable')?.split('.')[0] || null,
    isPersonal: (name, username) => name === username
  },
  // `useDataQualityReport.resolveSpace`: the segment is the username for the personal space.
  {
    pattern: '/data-quality/:space/:requestId',
    read: (_url, params) => params.space ?? null,
    isPersonal: (name, username) => name === username
  }
];

/**
 * Every flag an in-app destination depends on.
 *
 * Two sources, both derived rather than listed: the ROUTE's own flag, from the registry's nav
 * rows, and `sharedWorkspaces` when the URL names a space other than the viewer's personal one.
 * A link gated on anything less opens the unavailable page, or — for a shared space with shared
 * workspaces off — lands its reader in their own files with no word of where they were sent.
 *
 * @param link - An in-app path, optionally with a query (`/files?space=finance&prefix=…`).
 * @param username - The viewer, which is how two of the routes spell the personal space.
 * @returns The flags, deduplicated; empty for an ungated route (`/help`) or an unparseable link.
 *
 * @example
 * linkFlags('/query?refreshTable=finance.sales', 'alice'); // ['query', 'sharedWorkspaces']
 */
export function linkFlags(link: string, username: string | null): FeatureFlagKey[] {
  let url: URL;
  try {
    url = new URL(link, 'https://portal.invalid');
  } catch {
    return [];
  }
  const flags = new Set<FeatureFlagKey>();
  // `matchPath`, not string comparison, so a link matches its route exactly as the router does —
  // case-insensitively, and at a segment boundary.
  for (const [path, flag] of NAV_PATH_FLAGS) {
    if (matchPath({path, end: false}, url.pathname)) flags.add(flag);
  }
  for (const reader of SPACE_READERS) {
    const match = matchPath(reader.pattern, url.pathname);
    if (!match) continue;
    const name = reader.read(url, match.params);
    if (name && !reader.isPersonal(name, username)) flags.add('sharedWorkspaces');
  }
  return [...flags];
}
