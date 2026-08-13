// Named constants for the Data Explorer. The Athena polling cadence and the result page
// sizing are `features/catalog/` (SPEC-176) — this feature adds no second pager.

/**
 * Soft cap on open exploration tabs, enforced by refusal: `openTab` returns null and the
 * caller raises the cap dialog (SPEC-179 renders it). Mirrors `QUERY_TABS_MAX` — the two
 * surfaces have the same shape and no reason to disagree about how many is too many.
 */
export const EXPLORATION_TABS_MAX = 10;

/** sessionStorage key prefix for the per-user exploration tabs (full key: prefix + username). */
export const EXPLORATION_TABS_STORAGE_PREFIX = 's3portal.dataExplorer.tabs.';

/**
 * The alias a `sql` source's subquery is given: `FROM (<body>) AS t`.
 *
 * Trino requires a subquery in a FROM be aliased, and the alias is never shown — filters
 * and ordering reference columns unqualified, so nothing composed around it names this.
 */
export const SQL_SOURCE_ALIAS = 't';
