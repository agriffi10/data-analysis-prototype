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
 * Default data rows per query-results page when the user hasn't chosen a
 * value (SPEC-087). Drives GetQueryResults MaxResults (the first page
 * requests +1 to absorb the Athena SELECT header row, see getQueryResults)
 * and the Prev/Next pager. One display page = one fetch.
 */
export const DEFAULT_RESULTS_PAGE_SIZE = 100;

/** Smallest accepted "Rows per page" value (SPEC-087 FR-003). */
export const MIN_RESULTS_PAGE_SIZE = 1;

/**
 * Largest accepted "Rows per page" value — Athena's GetQueryResults returns at
 * most 1000 rows per call and one display page stays one fetch (SPEC-087).
 */
export const MAX_RESULTS_PAGE_SIZE = 1000;

/** sessionStorage key prefix for the per-user results page size (full key: prefix + username). */
export const QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX = 's3portal.query.resultsPageSize.';

/**
 * GetQueryResults MaxResults for the background total-row-count walk (SPEC-080) —
 * Athena's per-page maximum, so the walk makes the fewest round-trips. These
 * calls scan no extra bytes; they only re-read the already-computed result set.
 */
export const ROW_COUNT_PAGE_SIZE = 1000;

/** Cap on the per-user query-history JSON; the oldest entries beyond this are dropped. */
export const QUERY_HISTORY_MAX = 100;

/**
 * History-drawer entries per page (newest-first). Client-side only — the full
 * capped list is already in memory, so paging is a slice, not a fetch.
 */
export const QUERY_HISTORY_PAGE_SIZE = 7;

/**
 * Catalog-safe identifier rule — lowercase, leading letter, then [a-z0-9_],
 * 3–63 chars total. The same rule the pre-signup Lambda enforces for usernames
 * (= S3 prefix = Glue DB name); shared so view-name validation uses one source
 * of truth, never a hand-duplicated regex.
 */
export const CATALOG_IDENTIFIER_RE = /^[a-z][a-z0-9_]{2,62}$/;

/**
 * Human-readable form of `CATALOG_IDENTIFIER_RE` — the validation-hint text shown
 * when a name fails the rule. Exported so every dialog (view / table / shared
 * connection / partition key) shows one wording, not a hand-duplicated copy
 * (SPEC-106 FR-007).
 */
export const CATALOG_IDENTIFIER_RULE =
  'Use 3–63 characters: lowercase letters, digits, or underscore, starting with a letter.';

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

// Result-column sizing: MIN is the hard drag floor (small enough that a narrow
// column ellipsis-truncates its own header); STEP is the keyboard (Arrow)
// resize increment.
export const DEFAULT_COLUMN_WIDTH = 180; // px
export const MIN_COLUMN_WIDTH = 72; // px
export const COLUMN_RESIZE_STEP_PX = 16; // px per Arrow key press

/**
 * Editor/results layout presets (SPEC-079): the vertical split snaps to one of
 * three fixed proportions — no continuous drag.
 */
export type EditorLayoutPreset = 'editor' | 'even' | 'results';

export const DEFAULT_LAYOUT_PRESET: EditorLayoutPreset = 'even';

/** Editor-pane share of the editor+results column height, per preset. */
export const LAYOUT_PRESET_EDITOR_FRACTION: Record<EditorLayoutPreset, number> = {
  editor: 0.9,
  even: 0.5,
  results: 0.1
};

// Minimum-height floors so the extreme presets never collapse a pane to an
// unusable size (SPEC-079 FR-002). When a short viewport can't honor both,
// the editor floor wins (see useEditorLayout).
export const MIN_EDITOR_HEIGHT = 96; // px — editor floor (Results preset clamp)
export const MIN_RESULTS_HEIGHT = 120; // px — results-region floor (Editor preset clamp)

/** sessionStorage key prefix for the per-user layout preset (full key: prefix + username). */
export const QUERY_EDITOR_LAYOUT_STORAGE_PREFIX = 's3portal.query.editorLayout.';

/**
 * The boilerplate a brand-new first tab opens with (a `+` blank tab opens
 * empty). Shared by the workspace and the tabs-state factory.
 */
export const DEFAULT_SQL = `-- Reference tables as database.table (e.g. mydb.orders). Run with ⌘⏎.
SELECT 1;
`;
