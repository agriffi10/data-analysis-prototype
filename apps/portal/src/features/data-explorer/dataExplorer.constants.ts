// Named constants for the Data Explorer. The Athena polling cadence and the result page
// sizing are `features/catalog/` — this feature adds no second pager.

import type {CalcFunction, ColourOperator, ColourToken, CopyOptions, SurfaceToken} from './dataExplorer.types';
import type {Hex} from '../../lib/contrast';
import {PALETTE} from '../../lib/palette';
import type {EffectiveTheme} from '../../lib/theme.types';

/**
 * Soft cap on open exploration tabs, enforced by refusal: `openTab` returns null and the
 * caller raises the cap dialog. Mirrors `QUERY_TABS_MAX` — the two
 * surfaces have the same shape and no reason to disagree about how many is too many.
 */
export const EXPLORATION_TABS_MAX = 10;

/**
 * Rows fetched per page of results.
 *
 * A fixed size, unlike the Query workspace's user-controlled one: paging a result set costs
 * no additional bytes scanned (the `NextToken` walk reads an execution that has already run),
 * so there is nothing here for a user to trade off. The grid owns whatever this
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
 * How many previous query descriptions one tab remembers.
 *
 * A cap on a list of DESCRIPTIONS, not of result sets — each is a few hundred bytes and
 * the whole cursor is persisted with the tab, so the cap is about keeping a session's
 * `sessionStorage` document small rather than about memory. Oldest is dropped first.
 */
export const EXPLORER_FILTER_HISTORY_MAX = 25;

/**
 * The Calc panel's functions, in the ONE order they are ever listed.
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
 * answer to a question that was not asked, which is the same lie the filters keep the whole
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

// ---------------------------------------------------------------------------------------
// the palette. Nothing here is a NEW design token: these are the tokens `index.css` already
// defines, RESOLVED PER THEME from the one palette declaration. Two of this feature's
// requirements need their VALUES rather than their names — a gradient has to interpolate
// between two of them, and the contrast has to be computed from them — and a value is what a
// CSS variable cannot give a `useMemo`. Resolving instead of copying is why there is no
// second map to drift: `lib/contrast.test.ts` pins the declaration itself to `index.css`.
// ---------------------------------------------------------------------------------------

/** The tokens a formatted cell's own colours come from. */
const FORMATTING_TOKENS = [
  'text',
  'text-2',
  'accent-text',
  'success',
  'danger',
  'accent-soft',
  'success-soft',
  'warning-soft',
  'danger-soft'
] as const satisfies readonly (ColourToken | SurfaceToken)[];

/** The grid's own backgrounds, plus the selection fill a coloured cell can still sit under. */
const FORMATTING_SURFACE_TOKENS = ['surface', 'surface-2', 'accent-soft'] as const;

/**
 * The formatting palette's values in one theme.
 *
 * @param theme - The theme being painted.
 * @returns Each formatting token's hex, as `index.css` declares it for that theme.
 */
export function formattingTokenHex(theme: EffectiveTheme): Record<ColourToken | SurfaceToken, Hex> {
  return Object.fromEntries(FORMATTING_TOKENS.map((token) => [token, PALETTE[theme][token]])) as Record<
    ColourToken | SurfaceToken,
    Hex
  >;
}

/**
 * The surfaces a formatted cell can land on, which is what its colours are measured against.
 *
 * `surface` and `surface-2` are the grid's own backgrounds (the second is the hover and
 * zebra shade), and `accent-soft` is the SELECTION — a coloured cell is still selectable,
 * so the selection's fill is one of the backgrounds every foreground has to clear.
 *
 * @param theme - The theme being painted.
 * @returns Each surface's hex for that theme.
 */
export function formattingBaseSurfaces(theme: EffectiveTheme): Record<string, Hex> {
  return Object.fromEntries(FORMATTING_SURFACE_TOKENS.map((token) => [token, PALETTE[theme][token]]));
}

/**
 * The foregrounds a rule may choose, in the one order they are ever listed.
 *
 * **`warning` is deliberately absent.** It clears 4.5:1 on white (5.02) and fails on the
 * soft backgrounds this spec also introduces (4.49 on `accent-soft`, 4.39 on
 * `danger-soft`) — computed, not judged, and the test recomputes it. A palette entry that
 * is only sometimes legible is worse than one fewer colour, because nothing at the point
 * of choosing would tell the user which case they are in.
 */
export const FORMATTING_FOREGROUNDS: ColourToken[] = ['text', 'text-2', 'accent-text', 'success', 'danger'];

/** The backgrounds a rule may choose, and the endpoints a gradient may interpolate between. */
export const FORMATTING_BACKGROUNDS: SurfaceToken[] = ['accent-soft', 'success-soft', 'warning-soft', 'danger-soft'];

/** The one wording for each colour, so a swatch and its label never disagree. */
export const FORMATTING_COLOUR_LABELS: Record<ColourToken | SurfaceToken, string> = {
  text: 'Default',
  'text-2': 'Muted',
  'accent-text': 'Indigo',
  success: 'Green',
  danger: 'Red',
  'accent-soft': 'Indigo tint',
  'success-soft': 'Green tint',
  'warning-soft': 'Amber tint',
  'danger-soft': 'Red tint'
};

/** The colour rule operators, in the one order they are ever offered. */
export const COLOUR_OPERATORS: ColourOperator[] = ['=', '<>', '>', '>=', '<', '<=', 'like', 'ilike', 'regex'];

/**
 * The one wording for each colour operator.
 *
 * The first six deliberately match `FILTER_OPERATOR_LABELS` word for word: they are the
 * same comparisons, and a user who has just filtered on "greater than" should not have to
 * work out whether "is above" means the same thing. The last three are this spec's own.
 */
export const COLOUR_OPERATOR_LABELS: Record<ColourOperator, string> = {
  '=': 'equals',
  '<>': 'does not equal',
  '>': 'greater than',
  '>=': 'greater than or equal to',
  '<': 'less than',
  '<=': 'less than or equal to',
  like: 'matches (% and _)',
  ilike: 'matches, ignoring case',
  regex: 'matches a pattern'
};

/**
 * How many shades a gradient is quantised to.
 *
 * A gradient over a continuous range would emit a distinct colour per cell, which is a
 * distinct inline style per cell and a scale nobody can read anyway. Eleven steps is a
 * decile scale plus both ends.
 */
export const FORMATTING_GRADIENT_STEPS = 11;

/**
 * Longest pattern a `LIKE` / `ILIKE` / `REGEX` rule may carry.
 *
 * A user-authored pattern is compiled and run over every loaded cell, so a catastrophically
 * backtracking one would hang the tab. The cap bounds the input rather than the runtime —
 * it cannot make backtracking impossible, and the residual exposure is accepted: the
 * pattern is the user's own, it runs in their own browser over one page of rows, and a
 * reload clears it.
 */
export const FORMATTING_PATTERN_MAX = 200;

/** The most decimal places a numeric transformer will render (`toFixed`'s own ceiling is 100). */
export const NUMERIC_TRANSFORMER_MAX_PRECISION = 12;

/** Characters a binary transformer renders before it truncates. */
export const BINARY_TRANSFORMER_DEFAULT_MAX_LENGTH = 64;

/** The most a binary transformer will render, however high the cap is set. */
export const BINARY_TRANSFORMER_MAX_LENGTH = 512;

/**
 * What a strict numeric transformer shows for a value that is not a number.
 *
 * Deliberately not blank and deliberately not `0`: the cell HAS a value, and a transformer
 * that silently erased it would be indistinguishable from an empty column. Lenient mode
 * shows the value itself instead, which is the other honest answer.
 */
export const NUMERIC_TRANSFORMER_ERROR = '#ERR';

/** Appended to a binary rendering the cap cut short. */
export const TRUNCATION_INDICATOR = '…';

/**
 * The chrome for a bare `<select>`, re-exported from the shared layer that now owns it.
 *
 * It moved to `components/fieldStyles.ts` when a feature outside this one needed the same
 * string. Re-exported rather than re-pointed at six call sites: one definition either way, and
 * this keeps the move to the file that made it.
 */
export {SELECT_CLASS} from '../../components/fieldStyles';

/**
 * The alias a `sql` source's subquery is given: `FROM (<body>) AS t`.
 *
 * Trino requires a subquery in a FROM be aliased, and the alias is never shown — filters
 * and ordering reference columns unqualified, so nothing composed around it names this.
 */
export const SQL_SOURCE_ALIAS = 't';

/**
 * What a SQL NULL becomes in a clipboard format that has no null of its own.
 *
 * The same word the grid shows, so a paste reads the way the screen did. It is a token and
 * not a convention the format enforces, which is why `quoteValues` matters: with quoting on,
 * a value whose text is literally `NULL` arrives quoted and the two stop being confusable.
 */
export const COPY_NULL_TOKEN = 'NULL';

/** The header the row-number column carries in every copied format. */
export const ROW_NUMBER_HEADER = '#';

/**
 * The table a copied `INSERT` names.
 *
 * A PLACEHOLDER, on purpose. These rows are what a filter, an ordering and possibly a
 * `GROUP BY` produced, so naming the source table would render a statement that is valid,
 * runnable and wrong.
 */
export const COPY_SQL_TABLE = 'results';

/** Marks a NULL cell in the XML rendering, where an empty element already means `''`. */
export const COPY_XML_NULL_ATTRIBUTE = 'null';

/** The copy options Ctrl/Cmd+C uses: the plain paste a spreadsheet wants. */
export const PLAIN_COPY_OPTIONS: CopyOptions = {
  format: 'tsv',
  includeHeaders: false,
  includeRowNumbers: false,
  quoteValues: false
};

/** What the advanced dialog opens on: the plain copy, plus the headers a document wants. */
export const ADVANCED_COPY_DEFAULTS: CopyOptions = {...PLAIN_COPY_OPTIONS, includeHeaders: true};

/** The copy formats in the order the dialog offers them, with what each is for. */
export const COPY_FORMAT_LABELS: Record<CopyOptions['format'], string> = {
  tsv: 'Tab-separated (for spreadsheets)',
  csv: 'CSV',
  json: 'JSON',
  markdown: 'Markdown table',
  sql: 'SQL INSERT',
  xml: 'XML'
};
