// Named constants for the Data Explorer. The Athena polling cadence and the result page
// sizing are `features/catalog/` (SPEC-176) — this feature adds no second pager.

/**
 * Soft cap on open exploration tabs, enforced by refusal: `openTab` returns null and the
 * caller raises the cap dialog (SPEC-179 renders it). Mirrors `QUERY_TABS_MAX` — the two
 * surfaces have the same shape and no reason to disagree about how many is too many.
 */
export const EXPLORATION_TABS_MAX = 10;

/**
 * Rows fetched per page of results (SPEC-179 FR-009).
 *
 * A fixed size, unlike the Query workspace's user-controlled one: paging a result set costs
 * no additional bytes scanned (the `NextToken` walk reads an execution that has already run),
 * so there is nothing here for a user to trade off. SPEC-180's grid owns whatever this
 * becomes when the placeholder table goes.
 */
export const EXPLORATION_PAGE_SIZE = 100;

/**
 * The id of the region each tab controls, shared by the strip's `aria-controls` and the
 * panel's own `id`.
 *
 * One constant rather than two literals: a `tab` whose `aria-controls` names nothing is a
 * broken relationship no visual check catches, and the Query workspace pins the same pairing
 * with a test.
 */
export const EXPLORATION_TABPANEL_ID = 'exploration-tabpanel';

/** sessionStorage key prefix for the per-user exploration tabs (full key: prefix + username). */
export const EXPLORATION_TABS_STORAGE_PREFIX = 's3portal.dataExplorer.tabs.';

/**
 * The alias a `sql` source's subquery is given: `FROM (<body>) AS t`.
 *
 * Trino requires a subquery in a FROM be aliased, and the alias is never shown — filters
 * and ordering reference columns unqualified, so nothing composed around it names this.
 */
export const SQL_SOURCE_ALIAS = 't';
