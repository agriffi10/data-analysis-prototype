import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {formatBytes, normalizeColumnType} from './query.format';
import {
  deriveViewTargetDatabase,
  isResultProducingSql,
  isSchemaChangingSql,
  resolveRunStatements,
  sameSql,
  schemaChangingDatabase,
  splitSqlStatements,
  statementHint
} from './query.sql';
import {initialTabsState, migrateDraftToTabs, readTabsState, writeTabsState} from './queryTabs';
import {
  DEFAULT_COLUMN_WIDTH,
  DEFAULT_LAYOUT_PRESET,
  DEFAULT_RESULTS_PAGE_SIZE,
  DEFAULT_SQL,
  MAX_RESULTS_PAGE_SIZE,
  MIN_COLUMN_WIDTH,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT,
  MIN_RESULTS_PAGE_SIZE,
  QUERY_DRAFT_STORAGE_PREFIX,
  QUERY_EDITOR_LAYOUT_STORAGE_PREFIX,
  QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX,
  QUERY_TABS_MAX,
  QUERY_TABS_STORAGE_PREFIX
} from './query.constants';
import {partitionSchema} from './schema.partition';
import {buildSqlCompletions, createSqlCompletionProvider} from './sqlCompletions';
import type {DatabaseSchema} from './sqlCompletions';
import {act, renderHook} from '@testing-library/react';
import {useColumnWidths} from './useColumnWidths';
import {clampEditorHeight, useEditorLayout} from './useEditorLayout';
import {useQueryTabs} from './useQueryTabs';
import {clampPageSize, useResultsPageSize} from './useResultsPageSize';
import type {GlueTableSummary, QueryTabsState} from './query.types';

// ─── from query.format.test.ts ───
describe('query.format', () => {
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

  describe('formatBytes', () => {
    it('formats byte sizes with sensible units + precision', () => {
      expect(formatBytes(undefined)).toBe('—');
      expect(formatBytes(512)).toBe('512 B');
      expect(formatBytes(2048)).toBe('2.0 KB');
      expect(formatBytes(1_258_291)).toBe('1.2 MB');
      expect(formatBytes(53_687_091)).toBe('51 MB'); // ≥10 drops the decimal
    });
  });
});

// ─── from query.sql.test.ts ───
describe('query.sql', () => {
  describe('sameSql', () => {
    it('ignores trailing/leading whitespace and CRLF line endings', () => {
      // The editor commonly appends a trailing newline — a saved-query tab must not
      // read as "dirty" because of it.
      expect(sameSql('SELECT 1;', 'SELECT 1;\n')).toBe(true);
      expect(sameSql('SELECT 1;', '  SELECT 1;  ')).toBe(true);
      expect(sameSql('SELECT 1;\nSELECT 2;', 'SELECT 1;\r\nSELECT 2;')).toBe(true);
    });

    it('still detects a genuine edit (including interior whitespace)', () => {
      expect(sameSql('SELECT 1;', 'SELECT 2;')).toBe(false);
      expect(sameSql('SELECT a,b', 'SELECT a, b')).toBe(false);
    });
  });

  describe('isSchemaChangingSql', () => {
    it('detects DDL on table/view create/drop/alter (incl. CTAS, EXTERNAL, OR REPLACE)', () => {
      expect(isSchemaChangingSql('CREATE TABLE employees (id int)')).toBe(true);
      expect(isSchemaChangingSql('create external table t (id int)')).toBe(true);
      expect(isSchemaChangingSql('CREATE TABLE t AS SELECT * FROM src')).toBe(true);
      expect(isSchemaChangingSql('DROP TABLE t')).toBe(true);
      expect(isSchemaChangingSql('CREATE OR REPLACE VIEW v AS SELECT 1')).toBe(true);
    });

    it('detects DDL written under a leading comment (the missed-refresh regression)', () => {
      // The editor pre-fills a `-- …` comment; a CREATE under it must still count.
      expect(isSchemaChangingSql('-- make a table\nCREATE TABLE employees (id int)')).toBe(true);
      expect(isSchemaChangingSql('/* block */\n  create table t (id int)')).toBe(true);
    });

    it('does not flag non-schema statements', () => {
      expect(isSchemaChangingSql('SELECT * FROM employees')).toBe(false);
      expect(isSchemaChangingSql('-- just a comment\nSELECT 1')).toBe(false);
      expect(isSchemaChangingSql('INSERT INTO t VALUES (1)')).toBe(false);
    });
  });

  describe('deriveViewTargetDatabase (SPEC-077 FR-008)', () => {
    it('returns the single database of the body’s fully-qualified base tables', () => {
      expect(deriveViewTargetDatabase('SELECT * FROM mydb.orders')).toEqual({database: 'mydb'});
      // A self-join across the same db (FROM + JOIN) still resolves to one database.
      expect(deriveViewTargetDatabase('SELECT * FROM mydb.a JOIN mydb.b ON a.id = b.id')).toEqual({database: 'mydb'});
    });

    it('errors (never picks) when the body spans more than one database', () => {
      const target = deriveViewTargetDatabase('SELECT * FROM db_a.t JOIN db_b.u ON t.id = u.id');
      expect('error' in target && target.error).toMatch(/more than one database/i);
    });

    it('errors when no base table is database-qualified', () => {
      const target = deriveViewTargetDatabase('SELECT * FROM orders');
      expect('error' in target && target.error).toMatch(/qualify the tables/i);
    });

    it('does not treat unqualified CTE names as base tables', () => {
      // `recent` is a CTE (unqualified); only mydb.orders is a qualified base table.
      const sql = 'WITH recent AS (SELECT * FROM mydb.orders) SELECT * FROM recent';
      expect(deriveViewTargetDatabase(sql)).toEqual({database: 'mydb'});
    });
  });

  describe('schemaChangingDatabase (SPEC-077)', () => {
    it('extracts the target database from a qualified DDL statement', () => {
      expect(schemaChangingDatabase('CREATE EXTERNAL TABLE mydb.events (id int)')).toBe('mydb');
      expect(schemaChangingDatabase('DROP VIEW mydb.v1')).toBe('mydb');
      expect(schemaChangingDatabase('DROP TABLE IF EXISTS mydb.t')).toBe('mydb');
      // Skips the editor's pre-filled leading comment.
      expect(schemaChangingDatabase('-- header\nCREATE OR REPLACE VIEW mydb.v AS SELECT 1')).toBe('mydb');
    });

    it('returns null for a non-schema-changing statement or an unqualified target', () => {
      expect(schemaChangingDatabase('SELECT * FROM mydb.orders')).toBeNull();
      expect(schemaChangingDatabase('CREATE TABLE bare (id int)')).toBeNull();
    });
  });

  describe('splitSqlStatements (SPEC-078 FR-001)', () => {
    it('splits A; B; C into three statements in order', () => {
      const parsed = splitSqlStatements('SELECT 1; SELECT 2; SELECT 3');
      expect(parsed.map((s) => s.sql)).toEqual(['SELECT 1', 'SELECT 2', 'SELECT 3']);
      expect(parsed.map((s) => s.index)).toEqual([0, 1, 2]);
    });

    it('does not split on a semicolon inside a string literal', () => {
      expect(splitSqlStatements("SELECT ';' FROM t; SELECT 2").map((s) => s.sql)).toEqual([
        "SELECT ';' FROM t",
        'SELECT 2'
      ]);
      expect(splitSqlStatements("SELECT 'a;b' FROM mydb.t")).toHaveLength(1);
    });

    it('honors doubled-quote escapes inside \'…\' and "…"', () => {
      // The '' keeps the literal open across the ; that follows it.
      expect(splitSqlStatements("SELECT 'it''s; fine' FROM mydb.t")).toHaveLength(1);
      expect(splitSqlStatements('SELECT "we""ird; name" FROM mydb.t')).toHaveLength(1);
    });

    it('does not split inside quoted identifiers or backticks', () => {
      expect(splitSqlStatements('SELECT "col;umn" FROM mydb.t')).toHaveLength(1);
      expect(splitSqlStatements('CREATE TABLE mydb.t (`weird;name` int)')).toHaveLength(1);
    });

    it('does not split on semicolons inside -- line or /* */ block comments', () => {
      expect(splitSqlStatements('SELECT 1 -- not a split;\nFROM mydb.t')).toHaveLength(1);
      expect(splitSqlStatements('SELECT 1 /* ; still one ; */ FROM mydb.t')).toHaveLength(1);
    });

    it('yields no empty statement for trailing semicolons/whitespace', () => {
      expect(splitSqlStatements('SELECT 1;')).toHaveLength(1);
      expect(splitSqlStatements('SELECT 1; \n  ')).toHaveLength(1);
      expect(splitSqlStatements('SELECT 1;;;')).toHaveLength(1);
    });

    it('drops whitespace/comment-only segments', () => {
      expect(splitSqlStatements('SELECT 1; -- done\n; /* nothing */;')).toHaveLength(1);
      expect(splitSqlStatements('-- only a comment')).toHaveLength(0);
      expect(splitSqlStatements('   ')).toHaveLength(0);
    });

    it('yields exactly one statement for a single statement with no semicolon', () => {
      const parsed = splitSqlStatements('SELECT * FROM mydb.orders');
      expect(parsed).toHaveLength(1);
      expect(parsed[0].sql).toBe('SELECT * FROM mydb.orders');
    });

    it('records each statement’s trimmed source offsets in the buffer', () => {
      const buffer = '  SELECT 1;\n\nSELECT 2;';
      const [a, b] = splitSqlStatements(buffer);
      expect(buffer.slice(a.range.start, a.range.end)).toBe('SELECT 1');
      expect(buffer.slice(b.range.start, b.range.end)).toBe('SELECT 2');
    });

    it('keeps a statement’s interior comment inside its range', () => {
      const buffer = 'SELECT 1;\n-- setup\nCREATE TABLE mydb.t (id int);';
      const [, create] = splitSqlStatements(buffer);
      expect(buffer.slice(create.range.start, create.range.end)).toBe('-- setup\nCREATE TABLE mydb.t (id int)');
    });
  });

  describe('resolveRunStatements (SPEC-078 FR-006)', () => {
    const buffer = 'SELECT 1;\n\nSELECT 2;\n\nSELECT 3;';
    const statements = splitSqlStatements(buffer);

    it('a non-empty selection wins and is re-split per FR-001', () => {
      // Select the middle two statements.
      const start = buffer.indexOf('SELECT 2');
      const resolved = resolveRunStatements(buffer, statements, {start, end: buffer.length}, 0);
      expect(resolved.map((s) => s.sql)).toEqual(['SELECT 2', 'SELECT 3']);
      // Ranges are mapped back into the buffer, not the selection substring.
      expect(buffer.slice(resolved[0].range.start, resolved[0].range.end)).toBe('SELECT 2');
    });

    it('a partial selection runs exactly the selected text', () => {
      const start = buffer.indexOf('SELECT 1');
      const resolved = resolveRunStatements(buffer, statements, {start, end: start + 'SELECT'.length}, 0);
      expect(resolved.map((s) => s.sql)).toEqual(['SELECT']);
    });

    it('with no selection, resolves the statement whose range contains the cursor', () => {
      const cursor = buffer.indexOf('SELECT 2') + 3;
      expect(resolveRunStatements(buffer, statements, null, cursor).map((s) => s.sql)).toEqual(['SELECT 2']);
    });

    it('a cursor in the gap between statements falls back to the nearest preceding one', () => {
      const gap = buffer.indexOf('SELECT 2;') + 'SELECT 2;'.length + 1; // in the blank line after it
      expect(resolveRunStatements(buffer, statements, null, gap).map((s) => s.sql)).toEqual(['SELECT 2']);
    });

    it('a cursor before every statement falls back to the first', () => {
      const padded = '  \n' + buffer;
      const stmts = splitSqlStatements(padded);
      expect(resolveRunStatements(padded, stmts, null, 0).map((s) => s.sql)).toEqual(['SELECT 1']);
    });

    it('a sole statement resolves regardless of cursor position (today’s behavior)', () => {
      const solo = splitSqlStatements('SELECT 42');
      expect(resolveRunStatements('SELECT 42', solo, null, 9).map((s) => s.sql)).toEqual(['SELECT 42']);
    });

    it('an empty selection object is ignored (falls through to cursor resolution)', () => {
      const cursor = buffer.indexOf('SELECT 3') + 1;
      const resolved = resolveRunStatements(buffer, statements, {start: cursor, end: cursor}, cursor);
      expect(resolved.map((s) => s.sql)).toEqual(['SELECT 3']);
    });
  });

  describe('isResultProducingSql (SPEC-078 FR-007)', () => {
    it('is true for row-returning statements', () => {
      expect(isResultProducingSql('SELECT 1')).toBe(true);
      expect(isResultProducingSql('WITH x AS (SELECT 1) SELECT * FROM x')).toBe(true);
      expect(isResultProducingSql('SHOW TABLES IN mydb')).toBe(true);
      expect(isResultProducingSql('DESCRIBE mydb.t')).toBe(true);
      expect(isResultProducingSql('-- comment first\nSELECT 1')).toBe(true);
    });

    it('is false for DDL/DML whose outcome is history + status only', () => {
      expect(isResultProducingSql('CREATE TABLE mydb.t (id int)')).toBe(false);
      expect(isResultProducingSql('INSERT INTO mydb.t VALUES (1)')).toBe(false);
      expect(isResultProducingSql('DROP TABLE mydb.t')).toBe(false);
      expect(isResultProducingSql('MSCK REPAIR TABLE mydb.t')).toBe(false);
    });
  });

  describe('statementHint', () => {
    it('collapses whitespace and strips leading comments', () => {
      expect(statementHint('-- setup\nSELECT *\n  FROM mydb.t')).toBe('SELECT * FROM mydb.t');
    });

    it('truncates long statements with an ellipsis', () => {
      const hint = statementHint(`SELECT ${'a, '.repeat(30)}z FROM mydb.orders`);
      expect(hint.length).toBeLessThanOrEqual(30);
      expect(hint.endsWith('…')).toBe(true);
    });
  });
});

// A tab's link to the file it was opened from (SPEC-173): the key IS the identity.
const SAVED_LINK = {
  spaceId: 'personal',
  bucket: 'user-space',
  key: 'alice/saved_queries/Monthly revenue.sql',
  name: 'Monthly revenue'
};

// ─── from queryTabs.test.ts ───
describe('queryTabs', () => {
  const KEY = `${QUERY_TABS_STORAGE_PREFIX}alice`;

  function sample(): QueryTabsState {
    return {
      version: 1,
      tabs: [
        {id: 'a', label: 'Query 1', sql: 'SELECT 1;'},
        {id: 'b', label: 'Monthly revenue', sql: 'SELECT 2;', savedQuery: SAVED_LINK}
      ],
      activeTabId: 'b',
      nextQueryNumber: 2
    };
  }

  describe('queryTabs', () => {
    beforeEach(() => sessionStorage.clear());
    afterEach(() => {
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    });

    it('initialTabsState is a single Query 1 seeded with the boilerplate', () => {
      const s = initialTabsState();
      expect(s.tabs).toHaveLength(1);
      expect(s.tabs[0].label).toBe('Query 1');
      expect(s.tabs[0].sql).toBe(DEFAULT_SQL);
      expect(s.activeTabId).toBe(s.tabs[0].id);
      expect(s.nextQueryNumber).toBe(2);
    });

    it('round-trips a valid state through sessionStorage', () => {
      writeTabsState('alice', sample());
      expect(readTabsState('alice')).toEqual(sample());
    });

    it('returns null when no state exists', () => {
      expect(readTabsState('alice')).toBeNull();
    });

    it('keeps version 1 and IGNORES a pre-SPEC-173 savedQueryId — the tabs survive, the link does not', () => {
      // Bumping the version would have thrown the user's open buffers away in order to
      // discard one field, so the reader simply does not look at it.
      sessionStorage.setItem(
        KEY,
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Revenue', sql: 'SELECT 1;', savedQueryId: 'sq-1'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );

      const state = readTabsState('alice');

      expect(state?.tabs[0].sql).toBe('SELECT 1;');
      expect(state?.tabs[0].savedQuery).toBeUndefined();
    });

    it('rejects a malformed savedQuery link rather than half-linking a tab', () => {
      sessionStorage.setItem(
        KEY,
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Revenue', sql: 'SELECT 1;', savedQuery: {key: 'alice/saved_queries/a.sql'}}],
          activeTabId: 'a',
          nextQueryNumber: 2
        })
      );

      expect(readTabsState('alice')).toBeNull();
    });

    it('returns null (does not throw) on corrupt JSON', () => {
      sessionStorage.setItem(KEY, '{not json');
      expect(readTabsState('alice')).toBeNull();
    });

    it('rejects structurally invalid state (activeTabId references no tab)', () => {
      sessionStorage.setItem(
        KEY,
        JSON.stringify({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: ''}],
          activeTabId: 'missing',
          nextQueryNumber: 2
        })
      );
      expect(readTabsState('alice')).toBeNull();
    });

    it('rejects an empty tabs array and a wrong version', () => {
      sessionStorage.setItem(KEY, JSON.stringify({version: 1, tabs: [], activeTabId: 'a', nextQueryNumber: 2}));
      expect(readTabsState('alice')).toBeNull();
      sessionStorage.setItem(KEY, JSON.stringify({...sample(), version: 2}));
      expect(readTabsState('alice')).toBeNull();
    });

    it('is a no-op for an empty username', () => {
      writeTabsState('', sample());
      expect(sessionStorage.length).toBe(0);
      expect(readTabsState('')).toBeNull();
    });

    it('swallows storage failures rather than throwing', () => {
      const setItem = vi.fn(() => {
        throw new Error('QuotaExceededError');
      });
      const getItem = vi.fn(() => {
        throw new Error('SecurityError');
      });
      vi.stubGlobal('sessionStorage', {
        setItem,
        getItem,
        removeItem: vi.fn()
      });

      expect(() => writeTabsState('alice', sample())).not.toThrow();
      expect(readTabsState('alice')).toBeNull();
      expect(setItem).toHaveBeenCalled();
      expect(getItem).toHaveBeenCalled();
    });

    describe('migrateDraftToTabs', () => {
      it('seeds tab 1 from a SPEC-040 draft and removes the old key', () => {
        sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'SELECT migrated;');
        const state = migrateDraftToTabs('alice');
        expect(state).not.toBeNull();
        expect(state!.tabs).toHaveLength(1);
        expect(state!.tabs[0].sql).toBe('SELECT migrated;');
        // Old draft key is cleaned up.
        expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBeNull();
      });

      it('returns null when there is no draft', () => {
        expect(migrateDraftToTabs('alice')).toBeNull();
      });

      it('returns null when a tabs state already exists (does not clobber)', () => {
        writeTabsState('alice', sample());
        sessionStorage.setItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`, 'stale');
        expect(migrateDraftToTabs('alice')).toBeNull();
        // The stale draft is left alone (only migrated when tabs are absent).
        expect(sessionStorage.getItem(`${QUERY_DRAFT_STORAGE_PREFIX}alice`)).toBe('stale');
      });
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

    it('returns empty groups for an empty schema', () => {
      expect(partitionSchema([])).toEqual({tables: [], views: []});
    });

    it('preserves the incoming order within each group', () => {
      const {tables} = partitionSchema([table('b'), table('a'), table('c')]);
      expect(tables.map((t) => t.name)).toEqual(['b', 'a', 'c']);
    });
  });
});

// ─── from sqlCompletions.test.ts ───
describe('sqlCompletions', () => {
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

  // A single database's schema, the SPEC-077 completion-provider input shape.
  const alice: DatabaseSchema = {database: 'alice', tables: [orders, ordersView]};

  describe('buildSqlCompletions', () => {
    it('returns one fully-qualified item per table and view, kinded and labelled', () => {
      const items = buildSqlCompletions([alice]);
      const table = items.find((i) => i.label === 'alice.orders');
      const view = items.find((i) => i.label === 'alice.orders_summary');
      expect(table).toEqual({
        label: 'alice.orders',
        insertText: 'alice.orders',
        kind: 'table',
        detail: 'table · alice'
      });
      expect(view).toEqual({
        label: 'alice.orders_summary',
        insertText: 'alice.orders_summary',
        kind: 'view',
        detail: 'view · alice'
      });
    });

    it('emits one column item per column with its type and qualified table as detail', () => {
      const items = buildSqlCompletions([{database: 'alice', tables: [orders]}]);
      expect(items.filter((i) => i.kind === 'column')).toEqual([
        {label: 'id', insertText: 'id', kind: 'column', detail: 'bigint · alice.orders'},
        {label: 'total', insertText: 'total', kind: 'column', detail: 'double · alice.orders'}
      ]);
    });

    it('de-duplicates column names across tables and databases (keeps first declaration)', () => {
      const items = buildSqlCompletions([
        {database: 'alice', tables: [orders]},
        {database: 'bob', tables: [ordersView]}
      ]);
      const totals = items.filter((i) => i.kind === 'column' && i.label === 'total');
      expect(totals).toHaveLength(1);
      expect(totals[0].detail).toBe('double · alice.orders');
    });

    it('spans multiple databases, fully-qualifying each table', () => {
      const items = buildSqlCompletions([
        {database: 'alice', tables: [orders]},
        {database: 'bob', tables: [orders]}
      ]);
      const tables = items.filter((i) => i.kind === 'table').map((i) => i.label);
      expect(tables).toEqual(['alice.orders', 'bob.orders']);
    });

    it('yields no schema items for undefined or empty input', () => {
      expect(buildSqlCompletions(undefined)).toEqual([]);
      expect(buildSqlCompletions([])).toEqual([]);
    });

    it('yields the table item only for a zero-column table', () => {
      const items = buildSqlCompletions([
        {database: 'alice', tables: [{name: 'empty', columns: [], tableType: 'EXTERNAL_TABLE'}]}
      ]);
      expect(items).toEqual([
        {label: 'alice.empty', insertText: 'alice.empty', kind: 'table', detail: 'table · alice'}
      ]);
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
      const schemaRef = {current: [alice] as DatabaseSchema[] | undefined};
      const provider = createSqlCompletionProvider(fakeMonaco, schemaRef);
      const result = provider.provideCompletionItems(fakeModel, position, {} as never, {} as never);
      const suggestions = (result as unknown as {suggestions: Array<Record<string, unknown>>}).suggestions;

      const table = suggestions.find((s) => s.label === 'alice.orders');
      expect(table).toMatchObject({
        label: 'alice.orders',
        insertText: 'alice.orders',
        kind: 5, // Struct
        detail: 'table · alice',
        range: {startLineNumber: 1, endLineNumber: 1, startColumn: 1, endColumn: 3}
      });
      expect(suggestions.find((s) => s.label === 'id')).toMatchObject({kind: 3}); // Field
    });

    it('reads the latest schema from the ref on each call (no stale closure)', () => {
      const schemaRef = {current: undefined as DatabaseSchema[] | undefined};
      const provider = createSqlCompletionProvider(fakeMonaco, schemaRef);

      const empty = provider.provideCompletionItems(fakeModel, position, {} as never, {} as never);
      expect((empty as unknown as {suggestions: unknown[]}).suggestions).toEqual([]);

      schemaRef.current = [{database: 'alice', tables: [ordersView]}];
      const after = provider.provideCompletionItems(fakeModel, position, {} as never, {} as never);
      expect((after as unknown as {suggestions: Array<{label: string}>}).suggestions.map((s) => s.label)).toEqual([
        'alice.orders_summary',
        'total'
      ]);
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

// ─── from useEditorLayout.test.ts ───
describe('useEditorLayout', () => {
  const USER = 'alice';
  const KEY = `${QUERY_EDITOR_LAYOUT_STORAGE_PREFIX}${USER}`;

  beforeEach(() => {
    sessionStorage.clear();
  });

  describe('clampEditorHeight', () => {
    it('maps each preset to its proportion of a tall container', () => {
      // 1000px is tall enough that no floor kicks in except the results cap at 90%.
      expect(clampEditorHeight('even', 1000)).toBe(500);
      expect(clampEditorHeight('results', 1000)).toBe(100);
      // editor 90% of 1000 = 900 > 1000 - MIN_RESULTS_HEIGHT → capped.
      expect(clampEditorHeight('editor', 1000)).toBe(1000 - MIN_RESULTS_HEIGHT);
    });

    it('gives the editor its full 90% once the results floor is satisfied', () => {
      const h = MIN_RESULTS_HEIGHT * 10; // 90% leaves exactly the results floor
      expect(clampEditorHeight('editor', h)).toBe(h - MIN_RESULTS_HEIGHT);
      // Taller than that, 90% is below the cap → pure proportion.
      expect(clampEditorHeight('editor', 2000)).toBe(1800);
    });

    it('floors the editor at MIN_EDITOR_HEIGHT on the Results preset', () => {
      // 10% of 600 = 60 < MIN_EDITOR_HEIGHT.
      expect(clampEditorHeight('results', 600)).toBe(MIN_EDITOR_HEIGHT);
    });

    it('caps the editor so the results region keeps MIN_RESULTS_HEIGHT on the Editor preset', () => {
      // 90% of 400 = 360 > 400 - 120 = 280 → capped.
      expect(clampEditorHeight('editor', 400)).toBe(400 - MIN_RESULTS_HEIGHT);
    });

    it('lets the editor floor win when a short viewport cannot honor both floors', () => {
      // container - MIN_RESULTS_HEIGHT < MIN_EDITOR_HEIGHT → the editor floor wins;
      // never a negative/overlapping height.
      const short = MIN_EDITOR_HEIGHT + MIN_RESULTS_HEIGHT - 40;
      expect(clampEditorHeight('editor', short)).toBe(MIN_EDITOR_HEIGHT);
      expect(clampEditorHeight('results', short)).toBe(MIN_EDITOR_HEIGHT);
      expect(clampEditorHeight('even', 0)).toBe(MIN_EDITOR_HEIGHT);
    });
  });

  describe('useEditorLayout', () => {
    it('defaults to the even preset with no stored value', () => {
      const {result} = renderHook(() => useEditorLayout(USER, 1000));
      expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
      expect(result.current.editorHeight).toBe(500);
    });

    it('setPreset applies the new proportion and persists it per user', () => {
      const {result} = renderHook(() => useEditorLayout(USER, 1000));
      act(() => result.current.setPreset('results'));
      expect(result.current.preset).toBe('results');
      expect(result.current.editorHeight).toBe(100);
      expect(sessionStorage.getItem(KEY)).toBe('results');
    });

    it('restores a stored preset on mount (reload/tab-switch survival)', () => {
      sessionStorage.setItem(KEY, 'editor');
      const {result} = renderHook(() => useEditorLayout(USER, 1000));
      expect(result.current.preset).toBe('editor');
    });

    it('ignores a corrupt stored value and falls back to the default', () => {
      sessionStorage.setItem(KEY, 'sideways');
      const {result} = renderHook(() => useEditorLayout(USER, 1000));
      expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
    });

    it('scopes persistence to the username', () => {
      sessionStorage.setItem(`${QUERY_EDITOR_LAYOUT_STORAGE_PREFIX}bob`, 'editor');
      const {result} = renderHook(() => useEditorLayout(USER, 1000));
      expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
    });

    it('works without persisting when username is null', () => {
      const {result} = renderHook(() => useEditorLayout(null, 1000));
      act(() => result.current.setPreset('editor'));
      expect(result.current.preset).toBe('editor');
      expect(sessionStorage.length).toBe(0);
    });

    it('still selects (non-persistently) when sessionStorage throws', () => {
      const throwing = {
        getItem: () => {
          throw new Error('blocked');
        },
        setItem: () => {
          throw new Error('blocked');
        }
      };
      const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
      Object.defineProperty(globalThis, 'sessionStorage', {value: throwing, configurable: true});
      try {
        const {result} = renderHook(() => useEditorLayout(USER, 1000));
        expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
        act(() => result.current.setPreset('results'));
        expect(result.current.preset).toBe('results');
      } finally {
        if (original) Object.defineProperty(globalThis, 'sessionStorage', original);
      }
    });

    it('re-derives the height when the container resizes', () => {
      const {result, rerender} = renderHook(({height}: {height: number}) => useEditorLayout(USER, height), {
        initialProps: {height: 1000}
      });
      expect(result.current.editorHeight).toBe(500);
      rerender({height: 700});
      expect(result.current.editorHeight).toBe(350);
    });
  });
});

// ─── from useQueryTabs.test.ts ───
describe('useQueryTabs', () => {
  beforeEach(() => sessionStorage.clear());

  describe('useQueryTabs', () => {
    it('opens with a single Query 1 on a fresh session', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      expect(result.current.tabs).toHaveLength(1);
      expect(result.current.tabs[0].label).toBe('Query 1');
      expect(result.current.activeTab.id).toBe(result.current.tabs[0].id);
    });

    it('hands out monotonic Query N labels, never reusing across a close', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));

      act(() => void result.current.openTab()); // Query 2
      act(() => void result.current.openTab()); // Query 3
      expect(result.current.tabs.map((t) => t.label)).toEqual(['Query 1', 'Query 2', 'Query 3']);

      const q2 = result.current.tabs[1].id;
      act(() => result.current.closeTab(q2));
      expect(result.current.tabs.map((t) => t.label)).toEqual(['Query 1', 'Query 3']);

      act(() => void result.current.openTab()); // must be Query 4, not a reused 2
      expect(result.current.tabs.map((t) => t.label)).toEqual(['Query 1', 'Query 3', 'Query 4']);
    });

    it('blank + tab is empty and becomes active', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      act(() => void result.current.openTab());
      expect(result.current.activeTab.label).toBe('Query 2');
      expect(result.current.activeTab.sql).toBe('');
    });

    it('opens a named tab verbatim without consuming a Query N number (FR-009)', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      act(
        () =>
          void result.current.openTab({
            label: 'Monthly revenue',
            sql: 'SELECT * FROM rev;',
            savedQuery: SAVED_LINK
          })
      );
      const active = result.current.activeTab;
      expect(active.label).toBe('Monthly revenue');
      expect(active.sql).toBe('SELECT * FROM rev;');
      expect(active.savedQuery).toEqual(SAVED_LINK);

      // The counter was not incremented: the next blank tab is still Query 2.
      act(() => void result.current.openTab());
      expect(result.current.activeTab.label).toBe('Query 2');
    });

    it('isolates edits to the active tab', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      act(() => result.current.setActiveSql('SELECT first;'));
      const first = result.current.tabs[0].id;

      act(() => void result.current.openTab());
      act(() => result.current.setActiveSql('SELECT second;'));

      act(() => result.current.setActiveTab(first));
      expect(result.current.activeTab.sql).toBe('SELECT first;');
      expect(result.current.tabs[1].sql).toBe('SELECT second;');
    });

    it('refuses to open past QUERY_TABS_MAX, returning null', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      for (let i = result.current.tabs.length; i < QUERY_TABS_MAX; i++) {
        act(() => void result.current.openTab());
      }
      expect(result.current.tabs).toHaveLength(QUERY_TABS_MAX);

      let returned: string | null = 'sentinel';
      act(() => {
        returned = result.current.openTab();
      });
      expect(returned).toBeNull();
      expect(result.current.tabs).toHaveLength(QUERY_TABS_MAX);
    });

    it('never closes the last remaining tab', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      const only = result.current.tabs[0].id;
      act(() => result.current.closeTab(only));
      expect(result.current.tabs).toHaveLength(1);
    });

    it('activates the left neighbor when the active tab is closed', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      act(() => void result.current.openTab()); // Query 2 (active)
      act(() => void result.current.openTab()); // Query 3 (active)
      const [q1, q2, q3] = result.current.tabs.map((t) => t.id);
      expect(result.current.activeTabId).toBe(q3);

      act(() => result.current.setActiveTab(q2));
      act(() => result.current.closeTab(q2));
      // Left neighbor (Query 1) becomes active.
      expect(result.current.activeTabId).toBe(q1);
    });

    it('clearActive empties only the active tab', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      act(() => result.current.setActiveSql('SELECT keep;'));
      act(() => void result.current.openTab());
      act(() => result.current.setActiveSql('SELECT clearme;'));

      act(() => result.current.clearActive());
      expect(result.current.activeTab.sql).toBe('');
      expect(result.current.tabs[0].sql).toBe('SELECT keep;');
    });

    it('clearActive resets the tab name and unlinks any saved query', () => {
      const {result} = renderHook(() => useQueryTabs('alice'));
      // Open a saved-query tab: named label + saved-query link.
      act(
        () =>
          void result.current.openTab({
            label: 'Revenue',
            sql: 'SELECT 1',
            savedQuery: SAVED_LINK
          })
      );
      expect(result.current.activeTab.label).toBe('Revenue');
      expect(result.current.activeTab.savedQuery).toEqual(SAVED_LINK);

      act(() => result.current.clearActive());
      // Back to a fresh blank tab: empty SQL, a default "Query N" label, no link.
      expect(result.current.activeTab.sql).toBe('');
      expect(result.current.activeTab.label).toMatch(/^Query \d+$/);
      expect(result.current.activeTab.savedQuery).toBeUndefined();
    });

    it('persists across remount (restore from sessionStorage)', () => {
      const first = renderHook(() => useQueryTabs('alice'));
      act(() => void first.result.current.openTab({label: 'Saved', sql: 'X'}));
      expect(readTabsState('alice')?.tabs).toHaveLength(2);
      first.unmount();

      // A fresh mount restores the exact set + active tab.
      const second = renderHook(() => useQueryTabs('alice'));
      expect(second.result.current.tabs.map((t) => t.label)).toEqual(['Query 1', 'Saved']);
      expect(second.result.current.activeTab.label).toBe('Saved');
    });
  });
});

// ─── from useResultsPageSize.test.ts ───
describe('useResultsPageSize', () => {
  const USER = 'alice';
  const KEY = `${QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX}${USER}`;

  beforeEach(() => {
    sessionStorage.clear();
  });

  describe('clampPageSize', () => {
    it('passes integers in range through unchanged', () => {
      expect(clampPageSize(1)).toBe(1);
      expect(clampPageSize(250)).toBe(250);
      expect(clampPageSize(1000)).toBe(1000);
    });

    it('clamps out-of-range integers to the bounds (FR-003)', () => {
      expect(clampPageSize(0)).toBe(MIN_RESULTS_PAGE_SIZE);
      expect(clampPageSize(-5)).toBe(MIN_RESULTS_PAGE_SIZE);
      expect(clampPageSize(1001)).toBe(MAX_RESULTS_PAGE_SIZE);
      expect(clampPageSize(999999)).toBe(MAX_RESULTS_PAGE_SIZE);
    });

    it('rejects non-integers (FR-003: fractional/NaN never set a page size)', () => {
      expect(clampPageSize(2.5)).toBeNull();
      expect(clampPageSize(Number.NaN)).toBeNull();
      expect(clampPageSize(Number.POSITIVE_INFINITY)).toBeNull();
    });
  });

  describe('useResultsPageSize', () => {
    it('defaults to 100 with no stored value (FR-001/FR-005)', () => {
      const {result} = renderHook(() => useResultsPageSize(USER));
      expect(result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
    });

    it('setPageSize applies and persists the value per user (FR-005)', () => {
      const {result} = renderHook(() => useResultsPageSize(USER));
      act(() => result.current.setPageSize(250));
      expect(result.current.pageSize).toBe(250);
      expect(sessionStorage.getItem(KEY)).toBe('250');
    });

    it('clamps below-minimum and above-maximum values (FR-003)', () => {
      const {result} = renderHook(() => useResultsPageSize(USER));
      act(() => result.current.setPageSize(0));
      expect(result.current.pageSize).toBe(MIN_RESULTS_PAGE_SIZE);
      act(() => result.current.setPageSize(5000));
      expect(result.current.pageSize).toBe(MAX_RESULTS_PAGE_SIZE);
    });

    it('ignores non-integer input, keeping the last valid value (FR-003)', () => {
      const {result} = renderHook(() => useResultsPageSize(USER));
      act(() => result.current.setPageSize(50));
      act(() => result.current.setPageSize(12.7));
      act(() => result.current.setPageSize(Number.NaN));
      expect(result.current.pageSize).toBe(50);
      expect(sessionStorage.getItem(KEY)).toBe('50');
    });

    it('restores a stored value on mount (reload survival, FR-005)', () => {
      sessionStorage.setItem(KEY, '400');
      const {result} = renderHook(() => useResultsPageSize(USER));
      expect(result.current.pageSize).toBe(400);
    });

    it('falls back to the default on a malformed or out-of-range stored value (FR-005)', () => {
      sessionStorage.setItem(KEY, 'lots');
      expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
      sessionStorage.setItem(KEY, '99999');
      expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
      sessionStorage.setItem(KEY, '2.5');
      expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
    });

    it('scopes persistence to the username', () => {
      sessionStorage.setItem(`${QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX}bob`, '17');
      const {result} = renderHook(() => useResultsPageSize(USER));
      expect(result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
    });

    it('works without persisting when username is null', () => {
      const {result} = renderHook(() => useResultsPageSize(null));
      act(() => result.current.setPageSize(33));
      expect(result.current.pageSize).toBe(33);
      expect(sessionStorage.length).toBe(0);
    });

    it('still applies (non-persistently) when sessionStorage throws', () => {
      const throwing = {
        getItem: () => {
          throw new Error('blocked');
        },
        setItem: () => {
          throw new Error('blocked');
        }
      };
      const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
      Object.defineProperty(globalThis, 'sessionStorage', {value: throwing, configurable: true});
      try {
        const {result} = renderHook(() => useResultsPageSize(USER));
        expect(result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
        act(() => result.current.setPageSize(200));
        expect(result.current.pageSize).toBe(200);
      } finally {
        if (original) Object.defineProperty(globalThis, 'sessionStorage', original);
      }
    });
  });
});
