// Named constants for the query data layer.

/**
 * Athena execution polling cadence while a query is non-terminal — responsive
 * without hammering GetQueryExecution (most queries finish in seconds).
 */
export const POLL_INTERVAL_MS = 1_500;

/**
 * Stop polling after this long even if the query has not reached a terminal
 * state, so a stuck/forgotten execution can't poll forever. The query keeps
 * running in Athena (the workgroup's bytes-scanned cutoff is the real cost
 * guard); the UI can re-attach to the execution id later.
 */
export const MAX_POLL_DURATION_MS = 5 * 60_000;

/**
 * Default GetQueryResults page size — the service-level fallback when a
 * caller omits maxRows. The results UI passes QUERY_RESULTS_PAGE_SIZE instead.
 */
export const DEFAULT_MAX_ROWS = 100;

/**
 * Data rows per query-results page. Drives GetQueryResults MaxResults (the
 * first page requests +1 to absorb the Athena SELECT header row, see
 * getQueryResults) and the Prev/Next pager. Deliberately small so only one
 * page is ever mounted in the DOM.
 */
export const QUERY_RESULTS_PAGE_SIZE = 20;

/** Cap on the per-user query-history JSON; the oldest entries beyond this are dropped. */
export const QUERY_HISTORY_MAX = 100;

/**
 * History-drawer entries per page (newest-first). Client-side only — the full
 * capped list is already in memory, so paging is a slice, not a fetch.
 */
export const QUERY_HISTORY_PAGE_SIZE = 7;

/** The "View data" table preview opens SELECT * … LIMIT this. */
export const TABLE_PREVIEW_ROW_LIMIT = 10;

/**
 * Catalog-safe identifier rule — lowercase, leading letter, then [a-z0-9_],
 * 3–63 chars total. The same rule the pre-signup Lambda enforces for usernames
 * (= S3 prefix = Glue DB name); shared so view-name validation uses one source
 * of truth, never a hand-duplicated regex.
 */
export const CATALOG_IDENTIFIER_RE = /^[a-z][a-z0-9_]{2,62}$/;

/**
 * sessionStorage key prefix for the legacy per-user editor draft (full key:
 * prefix + username). Retained only for the one-time migration into the tabs
 * store (read once, then removed).
 */
export const QUERY_DRAFT_STORAGE_PREFIX = 's3portal.query.draft.';

/** sessionStorage key prefix for the per-user query-tabs state (full key: prefix + username). */
export const QUERY_TABS_STORAGE_PREFIX = 's3portal.query.tabs.';

/**
 * sessionStorage key prefix for the workspace-global active database (full
 * key: prefix + username → a database name). Default + fallback = the
 * personal database (username). NOT a per-tab field.
 */
export const QUERY_ACTIVE_DB_STORAGE_PREFIX = 's3portal.query.activeDatabase.';

/**
 * Soft cap on open query tabs, enforced by a dialog: the `+` stays enabled,
 * but openTab refuses past this count and the caller shows the "close a tab
 * first" dialog.
 */
export const QUERY_TABS_MAX = 10;

// Result-column sizing: MIN is the hard drag floor (small enough that a narrow
// column ellipsis-truncates its own header); STEP is the keyboard (Arrow)
// resize increment.
export const DEFAULT_COLUMN_WIDTH = 180; // px
export const MIN_COLUMN_WIDTH = 72; // px
export const COLUMN_RESIZE_STEP_PX = 16; // px per Arrow key press

/**
 * The boilerplate a brand-new first tab opens with (a `+` blank tab opens
 * empty). Shared by the workspace and the tabs-state factory.
 */
export const DEFAULT_SQL = `-- Write SQL against your database, then Run (⌘⏎).
SELECT 1;
`;
