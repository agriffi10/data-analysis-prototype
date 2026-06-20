// SPEC-034 named constants for the query data layer.

// FR-003: Athena execution polling cadence. Poll every 1.5s while a query is
// non-terminal — responsive without hammering GetQueryExecution (most queries
// finish in seconds).
export const POLL_INTERVAL_MS = 1_500;

// FR-003: stop polling after this long even if the query has not reached a
// terminal state, so a stuck/forgotten execution can't poll forever. The query
// itself keeps running in Athena (the workgroup's bytes-scanned cutoff, SPEC-032,
// is the real cost guard); the UI can re-attach to the execution id later.
export const MAX_POLL_DURATION_MS = 5 * 60_000;

// FR-004: default GetQueryResults page size — the service-level fallback when a
// caller omits maxRows. The results UI passes QUERY_RESULTS_PAGE_SIZE instead.
export const DEFAULT_MAX_ROWS = 100;

// SPEC-038 FR-001: the query-results pager shows this many data rows per page.
// Single source of truth for the results page size — drives GetQueryResults
// MaxResults (the first page requests +1 to absorb the Athena SELECT header row,
// see getQueryResults) and the Prev/Next pager. Deliberately small so only one
// page (≤20 rows) is ever mounted in the DOM.
export const QUERY_RESULTS_PAGE_SIZE = 20;

// FR-007: cap the per-user query-history JSON, dropping the oldest beyond this.
export const QUERY_HISTORY_MAX = 100;

// SPEC-042: the history drawer shows this many entries per page (newest-first),
// with a Prev/Next pager. Client-side only — the full capped-100 list is already
// in memory (useQueryHistory), so paging is a slice, not a fetch.
export const QUERY_HISTORY_PAGE_SIZE = 7;

// SPEC-040: sessionStorage key prefix for the per-user editor draft. The full
// key is `${QUERY_DRAFT_STORAGE_PREFIX}${username}`. Superseded by SPEC-041's
// tabs store — retained only for the one-time migration (read once, then removed).
export const QUERY_DRAFT_STORAGE_PREFIX = 's3portal.query.draft.';

// SPEC-041: sessionStorage key prefix for the per-user query-tabs state. Full
// key: `${QUERY_TABS_STORAGE_PREFIX}${username}`. Supersedes SPEC-040's single
// draft (migrated once into tab 1's sql, then the old key is removed).
export const QUERY_TABS_STORAGE_PREFIX = 's3portal.query.tabs.';

// SPEC-041: soft cap on open query tabs. Enforced by a dialog (FR-008): the `+`
// stays enabled, but openTab refuses past this count and the caller shows the
// "close a tab first" dialog. Closing a tab drops back below the cap.
export const QUERY_TABS_MAX = 10;

// SPEC-035/040/041: the boilerplate a brand-new first tab opens with (a `+` blank
// tab opens empty). Single source of truth, shared by the workspace and the
// tabs-state factory.
export const DEFAULT_SQL = `-- Write SQL against your database, then Run (⌘⏎).
SELECT 1;
`;
