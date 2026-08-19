import type {ExplorationSource} from './dataExplorer.types';

/**
 * Single source of truth for Data Explorer TanStack Query keys. Never hand-build a key
 * array — use these so consumers and the invalidation helpers stay in sync.
 *
 * Rooted at `['data-explorer']`, not `['query']` or `['catalog']` (the rule):
 * a namespace naming a feature the module does not belong to lets one feature's blanket
 * invalidation reach another's caches.
 *
 * The execution key ends in **the rendered SQL itself**. That is what makes
 * the cache the cost control: two explorations that render identically resolve to one
 * Athena execution, so changing a filter and changing it back is a cache hit rather than
 * a second bill. Keying by exploration id instead would bill every gesture.
 *
 * **THE SOURCE SITS IN FRONT OF THE SQL SO THE CACHE CAN BE EVICTED BY WHAT CHANGED.**
 * Keyed by SQL alone, the entry was unreachable except by its whole text: a table dropped
 * and rebuilt under the same name renders byte-identical SQL, so the Explorer answered from
 * the old execution — the old rows — for the rest of the session, with nothing on the page
 * that could ask it not to. The two source kinds are separated because only one of them can
 * be evicted precisely; see {@link explorationSourceScope}.
 */
export const explorerKeys = {
  all: ['data-explorer'] as const,
  execution: (scope: readonly [string, string, string], sql: string) =>
    [...explorerKeys.all, 'execution', ...scope, sql] as const,
  /** Every execution reading ONE table — the precise eviction, when the caller knows which. */
  table: (database: string, table: string) => [...explorerKeys.all, 'execution', 'table', database, table] as const,
  /** Every execution reading any table in this database, for a change that names no table. */
  database: (database: string) => [...explorerKeys.all, 'execution', 'table', database] as const,
  /** Every execution over a saved query, whose SQL may read any database at all. */
  sqlSources: () => [...explorerKeys.all, 'execution', 'sql'] as const
};

/**
 * The `[kind, database, table]` triple an exploration's source contributes to its execution key.
 *
 * A **table** source names its database, so an execution reading it can be found and dropped
 * when that database's catalog changes. A **saved query** source cannot: its body is arbitrary
 * SQL that may read any database, in any number, and this app has no parser. It is filed under
 * one scope so the eviction can take all of them together — over-eviction, deliberately, and
 * the cost of the alternative is a saved query that keeps showing rows from a table that no
 * longer holds them.
 *
 * Both the database and the table, because a caller that knows which table changed can then
 * evict only that one — a `CREATE VIEW` beside your exploration must not re-run it, and a
 * rebuild of the table you are reading must.
 *
 * @param source - The exploration's source.
 * @returns The three key segments, source kind first.
 */
export function explorationSourceScope(source: ExplorationSource): readonly [string, string, string] {
  return source.kind === 'table' ? ['table', source.database, source.table] : ['sql', source.label, ''];
}
