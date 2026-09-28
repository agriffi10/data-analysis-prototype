import {describe, expect, it} from 'vitest';
import {
  FILTER_OPERATORS,
  NO_VALUES_REFUSAL,
  TOO_MANY_VALUES_REFUSAL,
  filterChipLabel,
  isFilterOperator,
  isTextType,
  listFieldOf,
  numericLineRefusal,
  operatorsFor,
  parseFilterValues,
  readListField,
  sameQuery,
  setFilter
} from './explorationQueryOps';
import {EXPLORER_FILTER_VALUES_MAX} from './dataExplorer.constants';
import {emptyExplorationQuery} from './exploration';
import type {ColumnFilter, ExplorationQuery} from './dataExplorer.types';

const withFilters = (filters: ColumnFilter[]): ExplorationQuery => ({...emptyExplorationQuery(), filters});

describe('isTextType (FR-004)', () => {
  it('accepts both spellings and their parameterised forms, and nothing else', () => {
    for (const type of ['string', 'varchar', 'VARCHAR(20)', 'char(3)', 'char']) {
      expect(isTextType(type), type).toBe(true);
    }
    for (const type of ['bigint', 'date', 'decimal(10,2)', '']) {
      expect(isTextType(type), type).toBe(false);
    }
  });
});

describe('operatorsFor (FR-004)', () => {
  it('offers a text column everything, in offer order', () => {
    expect(operatorsFor('string')).toEqual([
      '=',
      '<>',
      '>',
      '>=',
      '<',
      '<=',
      'contains',
      'notContains',
      'startsWith',
      'endsWith',
      'in',
      'notIn',
      'isNull',
      'isNotNull',
      'isEmpty',
      'isNotEmpty'
    ]);
  });

  it('offers a numeric column the list tests but no text or empty one', () => {
    const numeric = operatorsFor('bigint');
    expect(numeric).toContain('in');
    expect(numeric).toContain('notIn');
    for (const operator of ['contains', 'notContains', 'startsWith', 'endsWith', 'isEmpty', 'isNotEmpty']) {
      expect(numeric, operator).not.toContain(operator);
    }
  });

  it('offers a date column the comparisons and the null tests only', () => {
    // `IN ('2026-01-01')` against a `date` is a type error just as `LIKE` is, because the
    // model quotes every non-numeric value.
    expect(operatorsFor('date')).toEqual(['=', '<>', '>', '>=', '<', '<=', 'isNull', 'isNotNull']);
  });
});

describe('isFilterOperator (the stored-document gate)', () => {
  it('admits every operator the app offers', () => {
    expect(FILTER_OPERATORS).toHaveLength(16);
    for (const operator of FILTER_OPERATORS) expect(isFilterOperator(operator), operator).toBe(true);
  });

  it('refuses a prototype key, which `in` would have admitted', () => {
    // The whole reason this is `Object.hasOwn`: `'toString' in table` is true, and a filter
    // carrying it renders into the middle of a statement rather than being turned back.
    for (const key of ['toString', 'constructor', 'valueOf', '__proto__', 'hasOwnProperty']) {
      expect(isFilterOperator(key), key).toBe(false);
    }
    expect(isFilterOperator('DROP')).toBe(false);
  });
});

describe('parseFilterValues (FR-004)', () => {
  it('keeps a text column’s lines verbatim, collapsing blanks and duplicates', () => {
    expect(parseFilterValues('NY\n\nNJ\nNY', 'string')).toEqual({values: ['NY', 'NJ']});
    expect(parseFilterValues(' NY ', 'string')).toEqual({values: [' NY ']});
  });

  it('numbers a bad line as the FIELD shows it, blank lines counted', () => {
    expect(parseFilterValues('1\nx\n3', 'number')).toEqual({refusal: numericLineRefusal(2)});
    // The blank line is still line 2, so the offending `x` is line 3 rather than line 2.
    expect(parseFilterValues('1\n\nx\n3', 'number')).toEqual({refusal: numericLineRefusal(3)});
  });

  it('trims a numeric column’s lines and ignores one that is then empty', () => {
    expect(parseFilterValues(' 10 \n   \n2.5', 'number')).toEqual({values: ['10', '2.5']});
  });

  it('splits on every line ending, so no value carries a carriage return', () => {
    // A `\r` left on a value is one the stored-document check refuses, which would drop
    // the whole tab on the next restore.
    expect(parseFilterValues('NY\r\nNJ', 'string')).toEqual({values: ['NY', 'NJ']});
  });

  it('refuses more than the cap counted after duplicates collapse, and leaves an empty field to its reader', () => {
    expect(parseFilterValues('\n\n', 'string')).toEqual({values: []});
    const lines = Array.from({length: EXPLORER_FILTER_VALUES_MAX}, (_, i) => `v${i}`);
    expect(parseFilterValues([...lines, 'v0'].join('\n'), 'string')).toEqual({values: lines});
    expect(parseFilterValues([...lines, 'one-more'].join('\n'), 'string')).toEqual({
      refusal: TOO_MANY_VALUES_REFUSAL
    });
  });
});

describe('readListField — the lines and the two boxes as one list', () => {
  const field = (text: string, empty = false, includesNull = false) => ({text, empty, includesNull});
  const lines = (count: number) => Array.from({length: count}, (_, i) => `v${i}`).join('\n');

  it.each([
    ['nothing at all', field(''), 'string', 'in', {refusal: NO_VALUES_REFUSAL}],
    ['only (empty)', field('', true), 'string', 'in', {values: ['']}],
    ['only NULL', field('', false, true), 'string', 'in', {values: [], includesNull: true}],
    ['NULL where the operator cannot list it', field('', false, true), 'string', 'notIn', {refusal: NO_VALUES_REFUSAL}],
    ['(empty) on a number column', field('', true), 'number', 'in', {refusal: NO_VALUES_REFUSAL}],
    ['a line, (empty) and NULL', field('a', true, true), 'string', 'in', {values: ['a', ''], includesNull: true}],
    ['1,000 lines plus (empty)', field(lines(EXPLORER_FILTER_VALUES_MAX), true), 'string', 'in', {refusal: TOO_MANY_VALUES_REFUSAL}],
    [
      '999 lines plus (empty) plus NULL',
      field(lines(EXPLORER_FILTER_VALUES_MAX - 1), true, true),
      'string',
      'in',
      {values: [...lines(EXPLORER_FILTER_VALUES_MAX - 1).split('\n'), ''], includesNull: true}
    ]
  ] as const)('reads %s', (_case, input, valueKind, operator, expected) => {
    expect(readListField(input, valueKind, operator)).toEqual(expected);
  });

  it('pre-fills from a stored list so reading it back gives the same list', () => {
    const stored: ColumnFilter = {column: 'c', operator: 'in', values: ['b', '', 'a'], includesNull: true};
    const prefilled = listFieldOf(stored);
    expect(prefilled).toEqual({text: 'b\na', empty: true, includesNull: true});
    expect(readListField(prefilled, 'string', 'in')).toEqual({values: ['b', 'a', ''], includesNull: true});
  });
});

describe('setFilter writes only the field the operator reads (FR-002)', () => {
  it('drops a value on the way to a list operator, and a list on the way back', () => {
    const listed = setFilter(withFilters([]), {column: 'c', operator: 'in', value: 'stale', values: ['a']});
    expect(listed.filters[0]).toEqual({column: 'c', operator: 'in', values: ['a']});
    const single = setFilter(listed, {column: 'c', operator: '=', value: 'x', values: ['a']});
    expect(single.filters[0]).toEqual({column: 'c', operator: '=', value: 'x'});
  });

  it('keeps includesNull on is one of and drops it on is not one of', () => {
    const kept = setFilter(withFilters([]), {column: 'c', operator: 'in', values: ['a'], includesNull: true});
    expect(kept.filters[0]).toEqual({column: 'c', operator: 'in', values: ['a'], includesNull: true});
    const dropped = setFilter(kept, {column: 'c', operator: 'notIn', values: ['a'], includesNull: true});
    expect(dropped.filters[0]).toEqual({column: 'c', operator: 'notIn', values: ['a']});
  });
});

describe('sameQuery over a list filter (FR-002)', () => {
  const listed = (values: string[], over: Partial<ColumnFilter> = {}) =>
    withFilters([{column: 'c', operator: 'in', values, ...over}]);

  it('is true however the values are arranged, and whatever stray field rides along', () => {
    expect(sameQuery(listed(['a', 'b']), listed(['b', 'a', 'a']))).toBe(true);
    // A document written before an operator changed can carry a `value` beside a list.
    // Comparing it would push a history entry for an apply that changed nothing.
    expect(sameQuery(listed(['a', 'b']), listed(['a', 'b'], {value: 'z'}))).toBe(true);
  });

  it('is false when the values themselves differ', () => {
    expect(sameQuery(listed(['a', 'b']), listed(['a', 'c']))).toBe(false);
  });

  it('is false when only NULL was added to the list, since that is a different statement', () => {
    expect(sameQuery(listed(['a']), listed(['a'], {includesNull: true}))).toBe(false);
  });
});

describe('filterChipLabel', () => {
  it.each<[string, ColumnFilter, string]>([
    ['a text value, quoted', {column: 'state', operator: '=', value: 'NY', valueKind: 'string'}, 'state equals “NY”'],
    ['a number compared, bare', {column: 'qty', operator: '>', value: '5', valueKind: 'number'}, 'qty greater than 5'],
    [
      'a list, in the renderer’s order',
      {column: 'brnd_name', operator: 'in', values: ['Zyrtec', 'Abilify']},
      'brnd_name is one of “Abilify”, “Zyrtec”'
    ],
    [
      'a long list, de-duplicated before it is counted',
      {column: 'c', operator: 'in', values: ['e', 'd', 'c', 'b', 'a', 'a']},
      'c is one of “a”, “b”, “c” and 2 more'
    ],
    [
      'a number list, bare',
      {column: 'qty', operator: 'notIn', values: ['7', '3'], valueKind: 'number'},
      'qty is not one of 3, 7'
    ],
    [
      'a text operator on a number column, quoted',
      {column: 'name', operator: 'contains', value: '5', valueKind: 'number'},
      'name contains “5”'
    ],
    ['an operator with no value', {column: 'last_name', operator: 'isEmpty'}, 'last_name is empty'],
    ['an empty string', {column: 'name', operator: '=', value: ''}, 'name equals (empty)'],
    [
      'a list naming (empty) and NULL, NULL last and counted',
      {column: 'c', operator: 'in', values: ['b', '', 'a'], includesNull: true},
      'c is one of (empty), “a”, “b” and 1 more'
    ],
    ['a short list naming NULL', {column: 'c', operator: 'in', values: ['a'], includesNull: true}, 'c is one of “a”, NULL'],
    ['spaces kept visible', {column: 'name', operator: '=', value: ' x '}, 'name equals “ x ”']
  ])('words %s', (_case, filter, label) => {
    expect(filterChipLabel(filter)).toBe(label);
  });
});
