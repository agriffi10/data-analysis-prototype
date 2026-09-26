// Named constants for the query workspace. The Athena polling cadence, the service-level
// page sizes and the result-column sizing live in `features/catalog/`; the
// saved-query page size and space memory in `features/saved-queries/`.

/**
 * Default data rows per query-results page when the user hasn't chosen a
 * value. Drives GetQueryResults MaxResults (the first page
 * requests +1 to absorb the Athena SELECT header row, see getQueryResults)
 * and the Prev/Next pager. One display page = one fetch.
 */
export const DEFAULT_RESULTS_PAGE_SIZE = 100;

/** Why Save results is refused for a statement that is not a query. */
export const SAVE_RESULTS_STATEMENT_REFUSAL =
  'Save results takes a query’s rows (SELECT, WITH or VALUES), not the output of SHOW, DESCRIBE or EXPLAIN.';

/** Smallest accepted "Rows per page" value. */
export const MIN_RESULTS_PAGE_SIZE = 1;

/**
 * Largest accepted "Rows per page" value — Athena's GetQueryResults returns at
 * most 1000 rows per call and one display page stays one fetch.
 */
export const MAX_RESULTS_PAGE_SIZE = 1000;

/** sessionStorage key prefix for the per-user results page size (full key: prefix + username). */
export const QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX = 's3portal.query.resultsPageSize.';

/** Cap on the per-user query-history JSON; the oldest entries beyond this are dropped. */
export const QUERY_HISTORY_MAX = 100;

/**
 * Byte budget for the same document, oldest entries dropped until it fits. The count alone let a
 * hundred long statements grow the file past the API's 3 MiB document cap, after which it could be
 * neither read nor written and history stopped recording. A third of that cap leaves room for the
 * escaping a read-back adds.
 */
export const QUERY_HISTORY_MAX_BYTES = 1024 * 1024;

/**
 * History-drawer entries per page (newest-first). Client-side only — the full
 * capped list is already in memory, so paging is a slice, not a fetch.
 */
export const QUERY_HISTORY_PAGE_SIZE = 7;

/**
 * sessionStorage key prefix for the legacy per-user editor draft (full key:
 * prefix + username). Retained only for the one-time migration into the tabs
 * store (read once, then removed).
 */
export const QUERY_DRAFT_STORAGE_PREFIX = 's3portal.query.draft.';

/** sessionStorage key prefix for the per-user query-tabs state (full key: prefix + username). */
export const QUERY_TABS_STORAGE_PREFIX = 's3portal.query.tabs.';

/**
 * Soft cap on open query tabs, enforced by a dialog: the `+` stays enabled,
 * but openTab refuses past this count and the caller shows the "close a tab
 * first" dialog.
 */
export const QUERY_TABS_MAX = 10;

/** Editor share of the editor+results column when nothing is stored. */
export const DEFAULT_EDITOR_FRACTION = 0.5;

/** Keyboard step, as a fraction of the column, per arrow press. */
export const EDITOR_SPLIT_KEY_STEP = 0.05;

/**
 * The lowest split an UNMEASURED column reports. The pixel floors below are the real
 * clamps, but they only exist once the column has been measured, and a split has
 * to be a usable number in (0, 1) before then — a stored 0 or 1 reads as invalid.
 */
export const MIN_EDITOR_FRACTION = 0.05;
/** The highest split an unmeasured column reports; the reasoning is on `MIN_EDITOR_FRACTION`. */
export const MAX_EDITOR_FRACTION = 0.95;

/**
 * The divider band's laid-out border-box height in px, subtracted from the
 * results floor so the clamp enforces the arithmetic the column actually lays
 * out. Sized so its content box clears the 24px WCAG minimum pointer target its
 * step buttons are drawn at, with the 1px rule above and below it. Those buttons
 * are sized in PX, not in Tailwind's rem spacing: the root font-size here is
 * 14px, so `h-6` is 21px and would miss the minimum silently.
 */
export const EDITOR_SPLIT_DIVIDER_HEIGHT = 28;

/**
 * The editor pane's floor in px, so a drag never collapses it to an unusable size.
 * When a short viewport can't honor both floors, this one wins.
 */
export const MIN_EDITOR_HEIGHT = 96;
/** The results region's floor in px; yields to `MIN_EDITOR_HEIGHT` on a short viewport. */
export const MIN_RESULTS_HEIGHT = 120;

/** sessionStorage key prefix for the per-user split (full key: prefix + username). */
export const QUERY_EDITOR_SPLIT_STORAGE_PREFIX = 's3portal.query.editorSplit.';

/**
 * The boilerplate a brand-new first tab opens with (a `+` blank tab opens
 * empty). Shared by the workspace and the tabs-state factory.
 */
export const DEFAULT_SQL = `-- Reference tables as database.table (e.g. mydb.orders). Run with ⌘⏎ or Ctrl+Enter.
SELECT 1;
`;
