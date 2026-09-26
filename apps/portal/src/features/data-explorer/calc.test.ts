import {describe, expect, it} from 'vitest';
import {calcResults, calcScopeText, percentageColumnName, percentageOfTotal, selectedCellValues} from './calc';
import {CALC_FUNCTIONS, CALC_NO_VALUE} from './dataExplorer.constants';
import type {CalcFunction, CellRange} from './dataExplorer.types';

// SPEC-182 FR-001: the aggregates themselves. Every answer here is computed over cells
// that exist only in the browser — no execution is involved at any point, which is what
// the panel test asserts by count.

const COLUMNS = [
  {name: 'id', index: 0},
  {name: 'note', index: 1},
  {name: 'qty', index: 2}
];

const ROWS: (string | null)[][] = [
  ['1', 'a', '10'],
  ['2', null, '20'],
  ['3', '', '30'],
  ['4', 'a', 'lots']
];

const all = (fns: CalcFunction[], values: (string | null)[], includeStrings = false) =>
  Object.fromEntries(calcResults(values, {functions: fns, includeStrings}).map((r) => [r.fn, r]));

const range = (fromRow: number, fromColumn: string, toRow: number, toColumn: string): CellRange => ({
  from: {row: fromRow, column: fromColumn},
  to: {row: toRow, column: toColumn}
});

describe('selectedCellValues', () => {
  it('reads a rectangle row-major, by column NAME and row-array index', () => {
    // Display order is free to differ from the execution's, so the value has to be read
    // through `index` — reading it by display position is the bug this pins.
    const reordered = [COLUMNS[2], COLUMNS[0]];
    expect(selectedCellValues([range(0, 'qty', 1, 'id')], reordered, ROWS)).toEqual(['10', '1', '20', '2']);
  });

  it('counts an overlapped cell once', () => {
    // Ctrl/Cmd+clicking inside an existing rectangle is one gesture away, and a value
    // counted twice moves an average without changing anything on screen.
    const values = selectedCellValues([range(0, 'id', 1, 'note'), range(0, 'id', 0, 'id')], COLUMNS, ROWS);
    expect(values).toEqual(['1', 'a', '2', null]);
  });

  it('keeps NULL and the empty string apart', () => {
    expect(selectedCellValues([range(1, 'note', 2, 'note')], COLUMNS, ROWS)).toEqual([null, '']);
  });

  it('ignores a range naming a column the result no longer has, and clamps to the loaded rows', () => {
    expect(selectedCellValues([range(0, 'gone', 1, 'id')], COLUMNS, ROWS)).toEqual([]);
    expect(selectedCellValues([range(2, 'id', 99, 'id')], COLUMNS, ROWS)).toEqual(['3', '4']);
  });
});

describe('the aggregates', () => {
  it('counts nulls, and never counts the empty string as one', () => {
    // The same distinction SPEC-180 FR-003 and SPEC-181 FR-002 make, in the third place it
    // has to survive: Athena hands every value back as a string, so nothing under this
    // layer can tell `NULL` from `''`.
    const results = all(['countNulls', 'count'], ['a', null, '', 'b'], true);
    expect(results.countNulls.value).toBe('1');
    expect(results.count.value).toBe('3');
  });

  it('ignores non-numeric cells rather than producing NaN, and says how many it skipped', () => {
    const results = all(['sum', 'avg', 'median'], ['10', 'lots', '20', null]);
    expect(results.sum.value).toBe('30');
    expect(results.avg.value).toBe('15');
    expect(results.median.value).toBe('15');
    // The NULL is not "skipped" — `countNulls` reports it. Skipped means a value that was
    // there and could not be a number.
    expect(results.sum.skipped).toBe(1);
    expect(Object.values(results).every((r) => !r.value.includes('NaN'))).toBe(true);
  });

  it('averages the two middle values of an even-length selection', () => {
    // `sorted[middle]` alone is right for odd lengths and silently wrong for even ones.
    expect(all(['median'], ['1', '2', '3', '10']).median.value).toBe('2.5');
    expect(all(['median'], ['1', '2', '3']).median.value).toBe('2');
  });

  it('rounds past floating-point noise', () => {
    // 0.1 + 0.2 renders as 0.30000000000000004, which reads as precision and is not.
    expect(all(['sum'], ['0.1', '0.2']).sum.value).toBe('0.3');
  });

  it('switches min/max between numeric and text comparison with the strings toggle', () => {
    const numeric = all(['min', 'max'], ['9', '10', 'apple']);
    expect(numeric.min.value).toBe('9');
    expect(numeric.max.value).toBe('10');
    expect(numeric.max.skipped).toBe(1);

    // Mixed: `9` sorts after `10` as text, which is the honest answer for a set that has
    // no numeric maximum at all.
    const mixed = all(['min', 'max'], ['9', '10', 'apple'], true);
    expect(mixed.min.value).toBe('10');
    expect(mixed.max.value).toBe('apple');
    expect(mixed.max.skipped).toBe(0);
  });

  it('keeps numeric order for an all-numeric selection with strings included', () => {
    // The toggle is on by default, and 9, 10 and 100 read as text would give min 10, max 9.
    const results = all(['min', 'max'], ['9', '10', '100', null], true);
    expect(results.min.value).toBe('9');
    expect(results.max.value).toBe('100');
  });

  it('reports the winning cell as it reads, never a rounded or reformatted copy of it', () => {
    // Sixteen-digit ids round at twelve significant digits, and a padded code loses its zero.
    const ids = all(['min', 'max'], ['1234567890123456', '1234567890123999'], true);
    expect(ids.max.value).toBe('1234567890123999');
    const codes = all(['min', 'max'], ['02134', '9', '1.50'], true);
    expect(codes.min.value).toBe('1.50');
    expect(codes.max.value).toBe('02134');
  });

  it('keeps sum, average and median numeric even with strings included', () => {
    // These have no mixed reading: an average of "unknown" is not a number, so the toggle
    // cannot make them consider text.
    const results = all(['sum', 'avg', 'median'], ['10', 'lots', '20'], true);
    expect(results.sum.value).toBe('30');
    expect(results.avg.value).toBe('15');
    expect(results.sum.skipped).toBe(1);
  });

  it('resolves a mode tie to the value that appears first in the selection', () => {
    expect(all(['mode'], ['b', 'a', 'b', 'a'], true).mode.value).toBe('b');
  });

  it('has no answer over an empty set, except a sum, which is zero', () => {
    const results = all(CALC_FUNCTIONS, ['lots', null]);
    // A count of nothing is 0 and an empty sum is 0; every other function shows the
    // no-value marker rather than a computed-looking zero.
    expect(results.count.value).toBe('0');
    expect(results.countDistinct.value).toBe('0');
    expect(results.countNulls.value).toBe('1');
    expect(results.sum.value).toBe('0');
    for (const fn of ['avg', 'min', 'max', 'median', 'mode'] as CalcFunction[]) {
      expect(results[fn].value).toBe(CALC_NO_VALUE);
    }
  });

  it('returns one result per requested function, in the order asked for', () => {
    expect(calcResults(['1'], {functions: ['max', 'count'], includeStrings: false}).map((r) => r.fn)).toEqual([
      'max',
      'count'
    ]);
  });

  it('refuses the same values the SQL renderer refuses as numbers', () => {
    // `numericValue` is `isBareNumeric`, deliberately: a panel that averaged values the
    // filter cannot compare numerically would disagree with the grid about which columns
    // are numeric.
    const results = all(['count', 'sum'], ['0x1f', 'Infinity', 'NaN', ' 5', '5']);
    expect(results.count.value).toBe('1');
    expect(results.sum.value).toBe('5');
    expect(results.sum.skipped).toBe(4);
  });
});

describe('the grouped result’s percentage column', () => {
  it('shares each value against the total of the values it was given', () => {
    expect(percentageOfTotal(['2', '6'])).toEqual(['25%', '75%']);
    expect(percentageOfTotal(['1', '1', '1'])).toEqual(['33.3%', '33.3%', '33.3%']);
  });

  it('shows no share rather than NaN or Infinity when there is no total', () => {
    // A grouped SUM whose page values are all zero — reachable, and a division that
    // rendered `NaN%` down the whole column would be the panel's most visible failure.
    expect(percentageOfTotal(['0', '0'])).toEqual([CALC_NO_VALUE, CALC_NO_VALUE]);
    expect(percentageOfTotal([])).toEqual([]);
  });

  it('gives a NULL or non-numeric cell no share, and lets the rest keep theirs', () => {
    expect(percentageOfTotal(['3', null, 'lots', '1'])).toEqual(['75%', CALC_NO_VALUE, CALC_NO_VALUE, '25%']);
  });

  it('names the aggregate AND the page in the column header', () => {
    // Both halves are load-bearing: only one page is ever in the browser, and with a SUM
    // in the grouping the proportion is of revenue rather than of rows.
    const name = percentageColumnName('sum_qty');
    expect(name).toContain('sum_qty');
    expect(name).toContain('this page');
  });

  it('says the Calc scope is selected cells on this page, singular and plural', () => {
    expect(calcScopeText(1)).toBe('1 selected cell on this page');
    expect(calcScopeText(4)).toBe('4 selected cells on this page');
  });
});
