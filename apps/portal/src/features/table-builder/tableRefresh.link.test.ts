import {describe, expect, it} from 'vitest';
import {parseRefreshLink} from './tableRefresh.link';

describe('parseRefreshLink', () => {
  it('parses the link SPEC-144 mints', () => {
    expect(parseRefreshLink('?refreshTable=sales.orders&removed=legacy_id,old_total')).toEqual({
      database: 'sales',
      tableName: 'orders',
      columns: ['legacy_id', 'old_total']
    });
  });

  it('works without the leading question mark and beside other parameters', () => {
    expect(parseRefreshLink('tab=2&refreshTable=alice.sales_2026&removed=gone&x=1')).toEqual({
      database: 'alice',
      tableName: 'sales_2026',
      columns: ['gone']
    });
  });

  it('decodes each name individually, so a comma inside one is not a separator', () => {
    // The exact string tbcommon.notify builds for these names.
    expect(parseRefreshLink('?refreshTable=sales.orders&removed=Order%20ID,a%26b,x%23y,co%2Cmma')).toEqual({
      database: 'sales',
      tableName: 'orders',
      columns: ['Order ID', 'a&b', 'x#y', 'co,mma']
    });
  });

  it('keeps names that are not catalog-safe identifiers (column names never are)', () => {
    expect(parseRefreshLink('?refreshTable=sales.orders&removed=id,ts,Amount,first%20name')?.columns).toEqual([
      'id',
      'ts',
      'Amount',
      'first name'
    ]);
  });

  it('caps the list at 20 names', () => {
    const names = Array.from({length: 25}, (_, i) => `col_${i}`);
    expect(parseRefreshLink(`?refreshTable=sales.orders&removed=${names.join(',')}`)?.columns).toHaveLength(20);
  });

  it('drops a name with a malformed escape but keeps the rest', () => {
    expect(parseRefreshLink('?refreshTable=sales.orders&removed=good,%E0%A4%A,also_good')?.columns).toEqual([
      'good',
      'also_good'
    ]);
  });

  // The parser reports what the URL said; the CALLER decides that an empty list is
  // not the link-borne state (QueryWorkspace), because gating confirm behind the
  // removals opt-in is only informed consent when the columns are named.
  it('reports an empty column list rather than inventing names', () => {
    expect(parseRefreshLink('?refreshTable=sales.orders')).toEqual({
      database: 'sales',
      tableName: 'orders',
      columns: []
    });
    expect(parseRefreshLink('?refreshTable=sales.orders&removed=')?.columns).toEqual([]);
    expect(parseRefreshLink('?refreshTable=sales.orders&removed=%E0%A4%A')?.columns).toEqual([]);
  });

  it.each([
    ['no refreshTable at all', '?removed=legacy_id'],
    ['an empty refreshTable', '?refreshTable=&removed=legacy_id'],
    ['no dot separator', '?refreshTable=orders'],
    ['a database that is not catalog-safe', '?refreshTable=Sales.orders'],
    ['a table that is not catalog-safe', '?refreshTable=sales.Orders'],
    ['a table with a path traversal', '?refreshTable=sales.../../etc'],
    ['an over-long table name', `?refreshTable=sales.${'a'.repeat(64)}`],
    ['a too-short table name', '?refreshTable=sales.ab']
  ])('ignores the parameters entirely when there is %s', (_label, search) => {
    expect(parseRefreshLink(search)).toBeNull();
  });
});
