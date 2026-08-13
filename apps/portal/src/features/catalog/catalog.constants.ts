// Named constants for the catalog data layer — properties of Athena and of result-column
// sizing, as opposed to the query workspace's own preferences (SPEC-176).

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
 * GetQueryResults MaxResults for the background total-row-count walk (SPEC-080) —
 * Athena's per-page maximum, so the walk makes the fewest round-trips. These
 * calls scan no extra bytes; they only re-read the already-computed result set.
 */
export const ROW_COUNT_PAGE_SIZE = 1000;

// Result-column sizing: MIN is the hard drag floor (small enough that a narrow
// column ellipsis-truncates its own header); STEP is the keyboard (Arrow)
// resize increment.
export const DEFAULT_COLUMN_WIDTH = 180; // px
export const MIN_COLUMN_WIDTH = 72; // px
// The drag CEILING. Not a layout constraint — a column wider than this has stopped being a
// column — and the value a focusable `role="separator"` needs for `aria-valuemax`, whose
// ARIA default of 100 would otherwise sit below every real width.
export const MAX_COLUMN_WIDTH = 1200; // px
export const COLUMN_RESIZE_STEP_PX = 16; // px per Arrow key press
