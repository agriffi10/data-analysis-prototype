// Named constants for the catalog data layer — properties of Athena and of result-column
// sizing, as opposed to the query workspace's own preferences.

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
 * Page size for the row-count walk, which now runs only where Athena does not count a
 * statement (a `SHOW`, a `DESCRIBE`, an `EXPLAIN`) or never reports a SELECT's count.
 * Athena's per-page maximum, so the walk makes the fewest calls. Each page scans nothing,
 * but it is not free: it is a billed API call that ships a page of rows only to be counted.
 */
export const ROW_COUNT_PAGE_SIZE = 1000;

/**
 * How long to wait before asking again for a SELECT whose count has not landed. AWS documents
 * that row statistics can be filled in a moment after a query completes; in production the
 * count was already there on the first read after SUCCEEDED every time it was measured, so
 * this schedule is the margin for the lag AWS describes. Seven asks across about a minute, and
 * only after the last one does the hook fall back to walking every page.
 */
export const ROW_COUNT_PENDING_DELAYS_MS: readonly number[] = [1_000, 2_000, 4_000, 8_000, 15_000, 30_000];

/** The width a result column starts at, in px. */
export const DEFAULT_COLUMN_WIDTH = 180;
/** The hard drag floor, in px — small enough that a narrow column ellipsis-truncates its own header. */
export const MIN_COLUMN_WIDTH = 72;
/**
 * The drag CEILING. Not a layout constraint — a column wider than this has stopped being a
 * column — and the value a focusable `role="separator"` needs for `aria-valuemax`, whose
 * ARIA default of 100 would otherwise sit below every real width.
 */
export const MAX_COLUMN_WIDTH = 1200; // px
/** How far one Arrow key press resizes a focused column, in px. */
export const COLUMN_RESIZE_STEP_PX = 16;
