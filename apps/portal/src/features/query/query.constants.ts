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
