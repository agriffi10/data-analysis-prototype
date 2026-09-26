import {describe, expect, it} from 'vitest';
import {act, renderHook} from '@testing-library/react';
import {normalizeColumnType, normalizeResultsName} from './catalog.format';
import {DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './catalog.constants';
import {useColumnWidths} from './useColumnWidths';
import {partitionSchema} from './schema.partition';
import type {GlueTableSummary} from './catalog.types';

// ─── from catalog.format.test.ts ───
describe('catalog.format', () => {
  describe('normalizeColumnType', () => {
    it('maps Athena/Presto engine names to their Glue/Hive DDL equivalents', () => {
      expect(normalizeColumnType('varchar')).toBe('string');
      expect(normalizeColumnType('integer')).toBe('int');
      expect(normalizeColumnType('real')).toBe('float');
      expect(normalizeColumnType('varbinary')).toBe('binary');
      expect(normalizeColumnType('VARCHAR')).toBe('string'); // case-insensitive
    });

    it('passes already-matching and complex/parameterized types through unchanged', () => {
      expect(normalizeColumnType('bigint')).toBe('bigint');
      expect(normalizeColumnType('boolean')).toBe('boolean');
      expect(normalizeColumnType('timestamp')).toBe('timestamp');
      expect(normalizeColumnType('decimal(10,2)')).toBe('decimal(10,2)');
      expect(normalizeColumnType('array(integer)')).toBe('array(integer)');
      expect(normalizeColumnType('')).toBe('');
    });
  });

  describe('normalizeResultsName', () => {
    it('appends the format’s extension, and does not double one the user already typed', () => {
      expect(normalizeResultsName('report', 'csv')).toBe('report.csv');
      expect(normalizeResultsName('report', 'parquet')).toBe('report.parquet');
      expect(normalizeResultsName('report', 'xlsx')).toBe('report.xlsx');
      expect(normalizeResultsName('report.json', 'json')).toBe('report.json');
      // Case is matched, and the name the user typed is returned as they typed it.
      expect(normalizeResultsName('report.CSV', 'csv')).toBe('report.CSV');
      expect(normalizeResultsName('  spaced  ', 'csv')).toBe('spaced.csv');
    });

    it('replaces another format’s extension rather than stacking onto it', () => {
      // The format is a control the user can change after typing a name, which is the whole
      // reason this is a replacement and not an append.
      expect(normalizeResultsName('report.csv', 'parquet')).toBe('report.parquet');
      expect(normalizeResultsName('report.XLSX', 'json')).toBe('report.json');
      expect(normalizeResultsName('report.parquet', 'csv')).toBe('report.csv');
    });

    it('leaves a dot-segment that is not one of the four formats alone', () => {
      // Guessing which trailing dot-segment was meant as a file type is how a name the user
      // chose quietly loses part of itself.
      expect(normalizeResultsName('sales.2026', 'csv')).toBe('sales.2026.csv');
      expect(normalizeResultsName('v1.2', 'parquet')).toBe('v1.2.parquet');
    });
  });
});

// ─── from useColumnWidths.test.ts ───
describe('useColumnWidths', () => {
  type Props = {id: string | null; count: number};

  function renderWidths(initial: Props) {
    return renderHook(({id, count}: Props) => useColumnWidths(id, count), {initialProps: initial});
  }

  describe('useColumnWidths', () => {
    it('defaults every column to DEFAULT_COLUMN_WIDTH', () => {
      const {result} = renderHook(() => useColumnWidths('exec-1', 3));
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
    });

    it('setWidth updates one column without touching the others', () => {
      const {result} = renderHook(() => useColumnWidths('exec-1', 3));
      act(() => result.current.setWidth(1, 300));
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, 300, DEFAULT_COLUMN_WIDTH]);
    });

    it('clamps setWidth at MIN_COLUMN_WIDTH', () => {
      const {result} = renderHook(() => useColumnWidths('exec-1', 2));
      act(() => result.current.setWidth(0, 10));
      expect(result.current.widths[0]).toBe(MIN_COLUMN_WIDTH);
    });

    it('resetColumn returns a single column to the default', () => {
      const {result} = renderHook(() => useColumnWidths('exec-1', 2));
      act(() => result.current.setWidth(0, 320));
      expect(result.current.widths[0]).toBe(320);
      act(() => result.current.resetColumn(0));
      expect(result.current.widths[0]).toBe(DEFAULT_COLUMN_WIDTH);
    });

    it('keeps widths across a re-render of the same execution (paging)', () => {
      const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
      act(() => result.current.setWidth(0, 320));
      rerender({id: 'exec-1', count: 2}); // same execution, e.g. Prev/Next
      expect(result.current.widths[0]).toBe(320);
    });

    it('keeps widths while the results reload and report no columns for a beat (a new page size)', () => {
      const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
      act(() => result.current.setWidth(0, 320));

      rerender({id: 'exec-1', count: 0});
      rerender({id: 'exec-1', count: 2});

      expect(result.current.widths[0]).toBe(320);
    });

    it('resets to defaults for a new execution id (a new query)', () => {
      const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
      act(() => result.current.setWidth(0, 320));

      rerender({id: 'exec-2', count: 2});
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
    });

    it('restores a prior execution’s widths when navigating back to it (tab switch)', () => {
      const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
      act(() => result.current.setWidth(0, 320));

      // Switch to another tab's query (defaults), then back to exec-1.
      rerender({id: 'exec-2', count: 3});
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);

      rerender({id: 'exec-1', count: 2});
      expect(result.current.widths).toEqual([320, DEFAULT_COLUMN_WIDTH]); // exec-1's widths survived
    });

    it('re-defaults when the same id reappears with a different column count', () => {
      const {result, rerender} = renderWidths({id: 'exec-1', count: 2});
      act(() => result.current.setWidth(1, 320));

      rerender({id: 'exec-1', count: 4});
      expect(result.current.widths).toEqual([
        DEFAULT_COLUMN_WIDTH,
        DEFAULT_COLUMN_WIDTH,
        DEFAULT_COLUMN_WIDTH,
        DEFAULT_COLUMN_WIDTH
      ]);
    });

    it('returns defaults and ignores setters when the execution id is null', () => {
      const {result} = renderHook(() => useColumnWidths(null, 2));
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
      act(() => result.current.setWidth(0, 320));
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
    });

    it('ignores out-of-range indices', () => {
      const {result} = renderHook(() => useColumnWidths('exec-1', 2));
      act(() => result.current.setWidth(5, 300));
      act(() => result.current.resetColumn(-1));
      expect(result.current.widths).toEqual([DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTH]);
    });
  });
});

// ─── from schema.partition.test.ts ───
describe('schema.partition', () => {
  const table = (name: string, tableType?: string): GlueTableSummary => ({
    name,
    columns: [],
    tableType
  });

  describe('partitionSchema', () => {
    it('splits VIRTUAL_VIEW into views and everything else into tables', () => {
      const {tables, views} = partitionSchema([
        table('sales', 'EXTERNAL_TABLE'),
        table('revenue', 'VIRTUAL_VIEW'),
        table('orders'), // no tableType → table
        table('summary', 'VIRTUAL_VIEW')
      ]);
      expect(tables.map((t) => t.name)).toEqual(['sales', 'orders']);
      expect(views.map((t) => t.name)).toEqual(['revenue', 'summary']);
    });
  });
});
