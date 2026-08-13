// Named constants for the Data Explorer. The Athena polling cadence and the result page
// sizing are `features/catalog/` (SPEC-176) — this feature adds no second pager.

import type {CalcFunction} from './dataExplorer.types';

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

/**
 * Width of the leading row-number column (px).
 *
 * Fixed and non-resizable — it is the grid's own furniture rather than one of the result's
 * columns, and it is the first sticky offset every pinned column is measured from.
 */
export const ROW_NUMBER_COLUMN_WIDTH = 56;

/**
 * Widest column the Text presentation will pad to, in characters.
 *
 * A cap rather than a measurement: text alignment is only useful while a line still fits
 * on a screen, and one 4 KB JSON cell would otherwise set the width for every row.
 */
export const TEXT_VIEW_MAX_COLUMN_CHARS = 48;

/** sessionStorage key prefix for the per-user exploration tabs (full key: prefix + username). */
export const EXPLORATION_TABS_STORAGE_PREFIX = 's3portal.dataExplorer.tabs.';

/**
 * How many previous query descriptions one tab remembers (SPEC-181 FR-006).
 *
 * A cap on a list of DESCRIPTIONS, not of result sets — each is a few hundred bytes and
 * the whole cursor is persisted with the tab, so the cap is about keeping a session's
 * `sessionStorage` document small rather than about memory. Oldest is dropped first.
 */
export const EXPLORER_FILTER_HISTORY_MAX = 25;

/**
 * The Calc panel's functions, in the ONE order they are ever listed (SPEC-182 FR-001).
 *
 * A fixed order rather than the order they were added: the panel is read repeatedly during
 * a selection gesture, and a list that reshuffles as functions come and go is a list nobody
 * can scan.
 */
export const CALC_FUNCTIONS: CalcFunction[] = [
  'count',
  'countDistinct',
  'countNulls',
  'sum',
  'avg',
  'min',
  'max',
  'median',
  'mode'
];

/** The two shown before anyone chooses: the questions a selection is usually asking. */
export const CALC_DEFAULT_FUNCTIONS: CalcFunction[] = ['count', 'countDistinct'];

/** The one wording for each function, so a checkbox and its result never disagree. */
export const CALC_FUNCTION_LABELS: Record<CalcFunction, string> = {
  count: 'Count',
  countDistinct: 'Count distinct',
  countNulls: 'Count nulls',
  sum: 'Sum',
  avg: 'Average',
  min: 'Minimum',
  max: 'Maximum',
  median: 'Median',
  mode: 'Mode'
};

/**
 * What a function with no answer shows.
 *
 * An average over no numeric cells has no value — and `0` would be a computed-looking
 * answer to a question that was not asked, which is the same lie FR-002 keeps the whole
 * panel away from.
 */
export const CALC_NO_VALUE = '—';

/**
 * Significant digits a computed number is rounded to before it is shown.
 *
 * Binary floating point makes `0.1 + 0.2` render as `0.30000000000000004`, which reads as
 * precision where it is noise. Twelve digits is far past anything a double carries
 * meaningfully and short of the artefacts.
 */
export const CALC_PRECISION = 12;

/**
 * The alias a `sql` source's subquery is given: `FROM (<body>) AS t`.
 *
 * Trino requires a subquery in a FROM be aliased, and the alias is never shown — filters
 * and ordering reference columns unqualified, so nothing composed around it names this.
 */
export const SQL_SOURCE_ALIAS = 't';
