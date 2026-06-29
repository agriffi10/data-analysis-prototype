import {describe, expect, it} from 'vitest';
import {buildSqlCompletions, createSqlCompletionProvider} from './sqlCompletions';
import type {GlueTableSummary} from './query.types';

const orders: GlueTableSummary = {
  name: 'orders',
  tableType: 'EXTERNAL_TABLE',
  columns: [
    {name: 'id', type: 'bigint'},
    {name: 'total', type: 'double'}
  ]
};
const ordersView: GlueTableSummary = {
  name: 'orders_summary',
  tableType: 'VIRTUAL_VIEW',
  columns: [{name: 'total', type: 'double'}]
};

describe('buildSqlCompletions', () => {
  it('returns one item per table and view, kinded and labelled', () => {
    const items = buildSqlCompletions([orders, ordersView]);
    const table = items.find((i) => i.label === 'orders');
    const view = items.find((i) => i.label === 'orders_summary');
    expect(table).toEqual({label: 'orders', insertText: 'orders', kind: 'table', detail: 'table'});
    expect(view).toEqual({
      label: 'orders_summary',
      insertText: 'orders_summary',
      kind: 'view',
      detail: 'view'
    });
  });

  it('emits one column item per column with its type and table as detail', () => {
    const items = buildSqlCompletions([orders]);
    expect(items.filter((i) => i.kind === 'column')).toEqual([
      {label: 'id', insertText: 'id', kind: 'column', detail: 'bigint · orders'},
      {label: 'total', insertText: 'total', kind: 'column', detail: 'double · orders'}
    ]);
  });

  it('de-duplicates column names across tables (keeps first declaration)', () => {
    const items = buildSqlCompletions([orders, ordersView]);
    const totals = items.filter((i) => i.kind === 'column' && i.label === 'total');
    expect(totals).toHaveLength(1);
    expect(totals[0].detail).toBe('double · orders');
  });

  it('yields no schema items for undefined or empty input', () => {
    expect(buildSqlCompletions(undefined)).toEqual([]);
    expect(buildSqlCompletions([])).toEqual([]);
  });

  it('yields the table item only for a zero-column table', () => {
    const items = buildSqlCompletions([{name: 'empty', columns: [], tableType: 'EXTERNAL_TABLE'}]);
    expect(items).toEqual([{label: 'empty', insertText: 'empty', kind: 'table', detail: 'table'}]);
  });
});

// Minimal fake Monaco surface the provider factory touches: the kind enum plus a
// model exposing getWordUntilPosition. No editor runtime involved.
const fakeMonaco = {
  languages: {
    CompletionItemKind: {Field: 3, Struct: 5, Interface: 7}
  }
} as unknown as Parameters<typeof createSqlCompletionProvider>[0];

const fakeModel = {
  getWordUntilPosition: () => ({startColumn: 1, endColumn: 3, word: 'or'})
} as unknown as Parameters<NonNullable<ReturnType<typeof createSqlCompletionProvider>['provideCompletionItems']>>[0];
const position = {lineNumber: 1, column: 3} as unknown as Parameters<
  NonNullable<ReturnType<typeof createSqlCompletionProvider>['provideCompletionItems']>
>[1];

describe('createSqlCompletionProvider', () => {
  it('maps descriptors onto Monaco items with a word-replacement range', () => {
    const schemaRef = {current: [orders] as GlueTableSummary[] | undefined};
    const provider = createSqlCompletionProvider(fakeMonaco, schemaRef);
    const result = provider.provideCompletionItems(fakeModel, position, {} as never, {} as never);
    const suggestions = (result as unknown as {suggestions: Array<Record<string, unknown>>}).suggestions;

    const table = suggestions.find((s) => s.label === 'orders');
    expect(table).toMatchObject({
      label: 'orders',
      insertText: 'orders',
      kind: 5, // Struct
      detail: 'table',
      range: {startLineNumber: 1, endLineNumber: 1, startColumn: 1, endColumn: 3}
    });
    expect(suggestions.find((s) => s.label === 'id')).toMatchObject({kind: 3}); // Field
  });

  it('reads the latest schema from the ref on each call (no stale closure)', () => {
    const schemaRef = {current: undefined as GlueTableSummary[] | undefined};
    const provider = createSqlCompletionProvider(fakeMonaco, schemaRef);

    const empty = provider.provideCompletionItems(fakeModel, position, {} as never, {} as never);
    expect((empty as unknown as {suggestions: unknown[]}).suggestions).toEqual([]);

    schemaRef.current = [ordersView];
    const after = provider.provideCompletionItems(fakeModel, position, {} as never, {} as never);
    expect((after as unknown as {suggestions: Array<{label: string}>}).suggestions.map((s) => s.label)).toEqual([
      'orders_summary',
      'total'
    ]);
  });
});
