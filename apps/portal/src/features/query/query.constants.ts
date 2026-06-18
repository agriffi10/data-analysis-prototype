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

// FR-004: default GetQueryResults page size. SPEC-038 sets the Prev/Next pager UX
// at 20 rows/page; this is the service-level default when a caller omits maxRows.
export const DEFAULT_MAX_ROWS = 100;

// FR-007: cap the per-user query-history JSON, dropping the oldest beyond this.
export const QUERY_HISTORY_MAX = 100;
