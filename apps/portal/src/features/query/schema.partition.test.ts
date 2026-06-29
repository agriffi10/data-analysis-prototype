import {describe, it, expect} from 'vitest';
import {partitionSchema} from './schema.partition';
import type {GlueTableSummary} from './query.types';

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

  it('returns empty groups for an empty schema', () => {
    expect(partitionSchema([])).toEqual({tables: [], views: []});
  });

  it('preserves the incoming order within each group', () => {
    const {tables} = partitionSchema([table('b'), table('a'), table('c')]);
    expect(tables.map((t) => t.name)).toEqual(['b', 'a', 'c']);
  });
});
