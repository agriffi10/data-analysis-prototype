import {CALC_NO_VALUE, CALC_PRECISION} from './dataExplorer.constants';
import {isBareNumeric} from './renderExplorationSql';
import type {CalcFunction, CalcPanelState, CalcResult, CellRange} from './dataExplorer.types';

// The Calc panel's arithmetic, kept apart from the panel for the reason
// `explorationQueryOps` is kept apart from the surfaces that call it: these answers are
// asserted about directly, and a median hidden inside a component is a median nobody
// tests over an even-length selection.
//
// **Nothing here renders SQL and nothing here can.** Calc aggregates the cells a user has
// SELECTED, and a selection exists only in the browser — so the alternative is a query per
// selection change, for a gesture as cheap as dragging across ten cells. That is why the
// panel says out loud what it computed over: its numbers describe loaded, selected
// cells and never the result set.

/** What one column contributes: its name, and where its values sit in a row array. */
type ValueColumn = {name: string; index: number};

/**
 * The values inside a selection, in row-major order.
 *
 * Coordinates are deduplicated rather than concatenated per rectangle, exactly as
 * `useCellSelection`'s own count is: overlapping ranges are easy to make (a Ctrl/Cmd+click
 * inside an existing rectangle) and a value counted twice would move an average.
 *
 * Row-major order is what makes `mode` deterministic — a tie resolves to whichever value
 * appears first reading the selection the way it is drawn.
 *
 * @param ranges - The selection's inclusive rectangles.
 * @param columns - The visible columns in display order, carrying their row-array index.
 * @param rows - The loaded page's rows, in the execution's column order.
 * @returns Every selected cell's raw value; `null` is SQL NULL.
 */
export function selectedCellValues(
  ranges: CellRange[],
  columns: ValueColumn[],
  rows: (string | null)[][]
): (string | null)[] {
  const positionOf = new Map(columns.map((column, position) => [column.name, position]));
  const selected = new Set<string>();
  for (const range of ranges) {
    const from = positionOf.get(range.from.column);
    const to = positionOf.get(range.to.column);
    // A range naming a column this result no longer has is skipped, not guessed at: the
    // selection resets on a column-set change, so this is only reachable mid-transition.
    if (from === undefined || to === undefined) continue;
    const firstRow = Math.max(Math.min(range.from.row, range.to.row), 0);
    const lastRow = Math.min(Math.max(range.from.row, range.to.row), rows.length - 1);
    for (let row = firstRow; row <= lastRow; row += 1) {
      for (let column = Math.min(from, to); column <= Math.max(from, to); column += 1) {
        selected.add(`${row}:${column}`);
      }
    }
  }

  const values: (string | null)[] = [];
  for (let row = 0; row < rows.length; row += 1) {
    for (let column = 0; column < columns.length; column += 1) {
      if (!selected.has(`${row}:${column}`)) continue;
      values.push(rows[row][columns[column].index] ?? null);
    }
  }
  return values;
}

/**
 * A cell's numeric value, or null when it does not hold a plain number.
 *
 * Deliberately the renderer's own `isBareNumeric` rather than a second numeric rule: both
 * are asking the one question "is this text a plain finite number", and a panel that
 * disagreed with the filter about which cells are numeric would let a user average a
 * column they cannot filter numerically. That predicate refuses `0x1f`, `Infinity`, `NaN`
 * and everything with a quote or a space in it, which is exactly the set that has no
 * business in an average either.
 *
 * @param value - The raw cell value.
 * @returns The number, or null for NULL and for anything non-numeric.
 */
function numericValue(value: string | null): number | null {
  if (value === null || !isBareNumeric(value)) return null;
  return Number(value);
}

/**
 * A computed number, rounded past floating-point noise and rendered without one.
 *
 * @param value - The number to show.
 * @returns Its display form.
 */
function formatNumber(value: number): string {
  return String(Number(value.toPrecision(CALC_PRECISION)));
}

/** Functions whose answer only exists over numbers, whatever the strings toggle says. */
const NUMERIC_ONLY: ReadonlySet<CalcFunction> = new Set<CalcFunction>(['sum', 'avg', 'median']);

function median(numbers: number[]): number {
  const sorted = [...numbers].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  // An even-length selection has no middle value, so the two either side are averaged —
  // the definition, and the case a naive `sorted[middle]` gets silently wrong.
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function mode(values: string[]): string | null {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  let best: string | null = null;
  let bestCount = 0;
  // Map iteration is insertion order, and the values arrive row-major — so a tie resolves
  // to the one that appears first in the selection rather than to whichever the engine
  // happened to hash first.
  for (const [value, count] of counts) {
    if (count > bestCount) {
      best = value;
      bestCount = count;
    }
  }
  return best;
}

/**
 * One function's answer over a selection.
 *
 * The strings toggle decides what the *considered* set is, and it is the panel's whole
 * honesty control: numbers-only considers the numeric cells and reports the
 * rest as `skipped`, where mixed considers every non-null cell and compares `min`/`max`
 * as text. `sum`, `avg` and `median` have no mixed reading at all — an average of
 * "unknown" is not a number — so they stay numeric either way and report their own skips.
 *
 * `countNulls` is the exception that must not be lost: it counts SQL NULL, never the empty
 * string, which is the same distinction the grid and the filters make, and the
 * third place it would be easy to drop (Athena hands every value back as a string, so
 * nothing below this layer can tell them apart).
 */
function computeOne(fn: CalcFunction, values: (string | null)[], includeStrings: boolean): CalcResult {
  const nulls = values.filter((value) => value === null).length;
  if (fn === 'countNulls') return {fn, value: String(nulls), skipped: 0};

  const present = values.filter((value): value is string => value !== null);
  const numbers = present.map(numericValue).filter((value): value is number => value !== null);
  const numericOnly = NUMERIC_ONLY.has(fn) || !includeStrings;
  const skipped = numericOnly ? present.length - numbers.length : 0;

  if (numericOnly) {
    // A count of nothing is `0` and an empty sum is `0` — both are real answers, and the
    // guard below must not swallow them. Every OTHER function has no answer at all over an
    // empty set and says so, rather than showing a computed-looking zero.
    if (fn === 'count') return {fn, value: String(numbers.length), skipped};
    if (fn === 'countDistinct') return {fn, value: String(new Set(numbers).size), skipped};
    if (fn === 'sum') return {fn, value: formatNumber(numbers.reduce((total, n) => total + n, 0)), skipped};
    if (numbers.length === 0) return {fn, value: CALC_NO_VALUE, skipped};
    switch (fn) {
      case 'avg':
        return {fn, value: formatNumber(numbers.reduce((total, n) => total + n, 0) / numbers.length), skipped};
      case 'median':
        return {fn, value: formatNumber(median(numbers)), skipped};
      // Reduced rather than spread into `Math.min`: a full page of a wide result is
      // thousands of cells, and a spread that long is an argument list, not a loop.
      case 'min':
        return {fn, value: formatNumber(numbers.reduce((low, n) => (n < low ? n : low))), skipped};
      case 'max':
        return {fn, value: formatNumber(numbers.reduce((high, n) => (n > high ? n : high))), skipped};
      default:
        return {fn, value: mode(numbers.map(String)) ?? CALC_NO_VALUE, skipped};
    }
  }

  if (fn === 'count') return {fn, value: String(present.length), skipped};
  if (fn === 'countDistinct') return {fn, value: String(new Set(present).size), skipped};
  if (present.length === 0) return {fn, value: CALC_NO_VALUE, skipped};
  // A selection of numbers alone keeps numeric order whatever the toggle says: text order
  // would put 10 before 9, and nothing here asked for text.
  if ((fn === 'min' || fn === 'max') && numbers.length === present.length) {
    const pick = numbers.reduce((best, n) => (fn === 'min' ? (n < best ? n : best) : n > best ? n : best));
    return {fn, value: formatNumber(pick), skipped};
  }
  // Text comparison, and it is the honest one here: a selection holding both `9` and
  // `apple` has no numeric maximum, and coercing would answer a different question.
  const sorted = [...present].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  if (fn === 'min') return {fn, value: sorted[0], skipped};
  if (fn === 'max') return {fn, value: sorted[sorted.length - 1], skipped};
  return {fn, value: mode(present) ?? CALC_NO_VALUE, skipped};
}

/**
 * The panel's answers, in the order its functions are listed.
 *
 * Pure and total: it never throws and never returns `NaN`, because these numbers are read
 * during a drag gesture and a panel that can fail takes the grid down with it.
 *
 * @param values - The selected cells' raw values, from `selectedCellValues`.
 * @param state - Which functions to compute, and whether strings are aggregated.
 * @returns One result per requested function.
 */
export function calcResults(values: (string | null)[], state: CalcPanelState): CalcResult[] {
  return state.functions.map((fn) => computeOne(fn, values, state.includeStrings));
}

/**
 * How the Calc panel describes what it aggregated.
 *
 * Every word of this is load-bearing. "Selected" bounds it to the cells the user picked,
 * "on this page" bounds it to the rows the browser is holding, and neither may be dropped
 * for brevity — a figure that sounds like it describes the table is the one dishonest
 * thing this panel could say, and the only thing stopping it is this sentence.
 *
 * @param count - How many cells the answers were computed over.
 * @returns The line shown above the results.
 */
export function calcScopeText(count: number): string {
  return `${count} selected ${count === 1 ? 'cell' : 'cells'} on this page`;
}

/**
 * What a grouped result's percentage column is called.
 *
 * **"On this page" is not a hedge, it is the truth.** Only the current page of a result is
 * in the browser, so a share computed here is a share of those rows — and a column headed
 * `% of count_all` beside a paged result would be read as a share of the table, which is
 * exactly the scale lie grouping exists to avoid. The aggregate is named too, because with
 * a `SUM` in the grouping the proportion is of revenue, not of rows.
 *
 * @param alias - The aggregate column the shares are taken of.
 * @returns The column's header.
 */
export function percentageColumnName(alias: string): string {
  return `% of ${alias} (this page)`;
}

/**
 * Each value's share of the total, as a percentage, computed over the values given.
 *
 * Client-side arithmetic over loaded rows, like the Calc panel above and for the same
 * reason: a whole-result percentage would need a second execution (a windowed one) for a
 * column the user asked to *see*, not to run.
 *
 * A non-numeric or absent value contributes nothing and shows no share, and a total of
 * zero yields no shares at all rather than a division that would render `Infinity` or
 * `NaN` across the column.
 *
 * @param values - The aggregate column's raw values, in row order.
 * @returns One display string per row, `CALC_NO_VALUE` where there is no share to show.
 */
export function percentageOfTotal(values: (string | null)[]): string[] {
  const numbers = values.map(numericValue);
  const total = numbers.reduce((sum: number, value) => sum + (value ?? 0), 0);
  if (total === 0) return values.map(() => CALC_NO_VALUE);
  return numbers.map((value) =>
    value === null ? CALC_NO_VALUE : `${formatNumber(Math.round((value / total) * 1000) / 10)}%`
  );
}
