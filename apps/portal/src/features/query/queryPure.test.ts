import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
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
  DEFAULT_EDITOR_FRACTION,
  DEFAULT_RESULTS_PAGE_SIZE,
  DEFAULT_SQL,
  EDITOR_SPLIT_DIVIDER_HEIGHT,
  EDITOR_SPLIT_KEY_STEP,
  MAX_RESULTS_PAGE_SIZE,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT,
  MIN_RESULTS_PAGE_SIZE,
  QUERY_DRAFT_STORAGE_PREFIX,
  QUERY_EDITOR_SPLIT_STORAGE_PREFIX,
  QUERY_RESULTS_PAGE_SIZE_STORAGE_PREFIX,
  QUERY_TABS_MAX,
  QUERY_TABS_STORAGE_PREFIX
} from './query.constants';
import {partitionSchema} from './schema.partition';
import {buildSqlCompletions, createSqlCompletionProvider} from './sqlCompletions';
import type {DatabaseSchema} from '../catalog/catalog.types';
import {act, renderHook} from '@testing-library/react';
import {clampEditorHeight, clampFraction, splitBounds, useEditorSplit} from './useEditorSplit';
import {useQueryTabs} from './useQueryTabs';
import {clampPageSize, useResultsPageSize} from './useResultsPageSize';
import type {QueryTabsState} from './query.types';
import type {GlueTableSummary} from '../catalog/catalog.types';

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

    it('records each statement’s trimmed source offsets in the buffer', () => {
      const buffer = '  SELECT 1;\n\nSELECT 2;';
      const [a, b] = splitSqlStatements(buffer);
      expect(buffer.slice(a.range.start, a.range.end)).toBe('SELECT 1');
      expect(buffer.slice(b.range.start, b.range.end)).toBe('SELECT 2');
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
  });

  describe('isResultProducingSql (SPEC-078 FR-007)', () => {
    it('is true for row-returning statements', () => {
      expect(isResultProducingSql('SELECT 1')).toBe(true);
      expect(isResultProducingSql('WITH x AS (SELECT 1) SELECT * FROM x')).toBe(true);
      expect(isResultProducingSql('SHOW TABLES IN mydb')).toBe(true);
      expect(isResultProducingSql('DESCRIBE mydb.t')).toBe(true);
      expect(isResultProducingSql('-- comment first\nSELECT 1')).toBe(true);
    });
  });

  describe('statementHint', () => {
    it('collapses whitespace and strips leading comments', () => {
      expect(statementHint('-- setup\nSELECT *\n  FROM mydb.t')).toBe('SELECT * FROM mydb.t');
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

    it('is a no-op for an empty username', () => {
      writeTabsState('', sample());
      expect(Object.keys(sessionStorage)).toEqual([]);
      expect(readTabsState('')).toBeNull();
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
  });
});

// ─── from useEditorSplit.test.ts ───
describe('useEditorSplit', () => {
  const USER = 'alice';
  const KEY = `${QUERY_EDITOR_SPLIT_STORAGE_PREFIX}${USER}`;
  // The retired preset key, spelled out because its constant is gone. A value
  // written under it ('even') is not a number, so reading it would poison the
  // split; the guard is that it is never read at all.
  const OLD_KEY = 's3portal.query.editorLayout.alice';

  beforeEach(() => {
    sessionStorage.clear();
  });

  describe('clampEditorHeight', () => {
    it('maps a fraction to its share of a tall column', () => {
      expect(clampEditorHeight(0.5, 1000)).toBe(500);
      expect(clampEditorHeight(0.1, 1000)).toBe(100);
    });

    it('caps the editor so the results keep their floor and the divider', () => {
      // 0.9 of 400 = 360, but the results floor plus the divider need 144.
      expect(clampEditorHeight(0.9, 400)).toBe(400 - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT);
      // Tall enough that 0.9 sits below the cap → pure proportion.
      expect(clampEditorHeight(0.9, 2000)).toBe(1800);
    });

    it('gives the editor its floor on a column too short for both floors', () => {
      // 96 + 120 + 24 = 240 is the shortest column that honours both.
      expect(clampEditorHeight(0.5, 200)).toBe(MIN_EDITOR_HEIGHT);
      expect(200 - clampEditorHeight(0.5, 200) - EDITOR_SPLIT_DIVIDER_HEIGHT).toBeGreaterThanOrEqual(0);
      // And on a column shorter than the floor itself, the editor takes what is
      // left rather than overrunning it.
      expect(50 - clampEditorHeight(0.5, 50) - EDITOR_SPLIT_DIVIDER_HEIGHT).toBeGreaterThanOrEqual(0);
    });

    it('never lets the two panes and the divider exceed the column, and agrees with the bounds', () => {
      // jsdom lays nothing out, so the property FR-001 states about the rendered
      // column — editor + divider + results == column — is asserted as arithmetic.
      // The sweep starts one pixel above the divider's own height, which is where
      // a column stops counting as measured; below that both functions answer from
      // the unmeasured branch and there is no column to contain anything.
      for (let height = EDITOR_SPLIT_DIVIDER_HEIGHT + 1; height <= 4000; height += 37) {
        for (const fraction of [0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999]) {
          const editor = clampEditorHeight(fraction, height);
          const results = height - editor - EDITOR_SPLIT_DIVIDER_HEIGHT;
          // 96 + 120 + 24 is the shortest column that can honour both floors;
          // under it the editor floor wins, but never past the column itself.
          expect(results).toBeGreaterThanOrEqual(
            height >= MIN_EDITOR_HEIGHT + MIN_RESULTS_HEIGHT + EDITOR_SPLIT_DIVIDER_HEIGHT ? MIN_RESULTS_HEIGHT : 0
          );
          // The ARIA value the divider reports is derived from the clamped
          // fraction while the pane height comes from the pixel clamp; the two
          // describing different splits is the defect this pins.
          expect(editor).toBe(Math.round(height * clampFraction(fraction, height)));
        }
      }
    });
  });

  describe('useEditorSplit', () => {
    it('defaults to an even split and persists a set fraction under the new key', () => {
      const {result} = renderHook(() => useEditorSplit(USER, 1000));

      expect(result.current.fraction).toBe(DEFAULT_EDITOR_FRACTION);
      expect(result.current.editorHeight).toBe(500);

      act(() => result.current.setFraction(0.3));
      expect(result.current.editorHeight).toBe(300);
      expect(sessionStorage.getItem(KEY)).toBe('0.3');
      expect(sessionStorage.getItem(OLD_KEY)).toBeNull();
    });

    it('never READS the retired preset key', () => {
      // The old key holds the string 'even', which is not a number — reading it
      // would send the split to the default on every mount of an existing
      // session. Recording through a stubbed global, NOT a Storage.prototype
      // spy: a prototype spy records zero calls here (measured), so a guard
      // built on one is `[].every(...)` and passes whatever the hook read.
      const reads: string[] = [];
      const store: Record<string, string> = {[OLD_KEY]: 'even'};
      vi.stubGlobal('sessionStorage', {
        getItem: (key: string) => {
          reads.push(key);
          return store[key] ?? null;
        },
        setItem: (key: string, value: string) => {
          store[key] = value;
        }
      });
      // The recorder is really in place — otherwise `reads` stays empty and the
      // assertion below holds vacuously.
      sessionStorage.getItem('probe');
      expect(reads).toEqual(['probe']);

      renderHook(() => useEditorSplit(USER, 1000));

      expect(reads).toContain(KEY);
      expect(reads).not.toContain(OLD_KEY);
      vi.unstubAllGlobals();
    });

    it('reads a stored fraction back, and ignores one that is not a finite fraction', () => {
      sessionStorage.setItem(KEY, '0.25');
      expect(renderHook(() => useEditorSplit(USER, 1000)).result.current.editorHeight).toBe(250);

      for (const junk of ['even', '', '2', '-1', 'NaN', 'Infinity']) {
        sessionStorage.setItem(KEY, junk);
        const {result} = renderHook(() => useEditorSplit(USER, 1000));
        expect(result.current.fraction).toBe(DEFAULT_EDITOR_FRACTION);
      }
    });

    it('still drags with storage throwing', () => {
      vi.stubGlobal('sessionStorage', {
        getItem: () => {
          throw new Error('storage disabled');
        },
        setItem: () => {
          throw new Error('quota exceeded');
        }
      });
      // The stub is really in place — a spy on Storage.prototype is NOT, because
      // jsdom's storage does not dispatch through it, and the degrade path then
      // never runs while the test still passes.
      expect(() => sessionStorage.getItem('x')).toThrow();

      const {result} = renderHook(() => useEditorSplit(USER, 1000));
      expect(result.current.fraction).toBe(DEFAULT_EDITOR_FRACTION);
      act(() => result.current.setFraction(0.3));
      expect(result.current.editorHeight).toBe(300); // applied, just not persisted

      vi.unstubAllGlobals();
    });

    it('reads nor writes anything without a username', () => {
      sessionStorage.setItem(KEY, '0.8'); // another user's split is not this one's
      const {result} = renderHook(() => useEditorSplit(null, 1000));

      expect(result.current.fraction).toBe(DEFAULT_EDITOR_FRACTION);
      act(() => result.current.setFraction(0.3));
      expect(result.current.editorHeight).toBe(300);
      // Exactly the seeded key, so a write to a `…editorSplit.null` key is caught
      // rather than passing because it landed somewhere nobody looked.
      expect(Object.keys(sessionStorage)).toEqual([KEY]);
      expect(sessionStorage.getItem(KEY)).toBe('0.8');
    });

    it('re-clamps a stored fraction against a shrinking column without rewriting it', () => {
      const {result, rerender} = renderHook(({h}) => useEditorSplit(USER, h), {initialProps: {h: 1000}});
      act(() => result.current.setFraction(0.8));
      expect(result.current.editorHeight).toBe(800);

      // 0.8 of 400 would leave the results region 6px under the divider.
      rerender({h: 400});
      expect(result.current.editorHeight).toBe(400 - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT);
      expect(sessionStorage.getItem(KEY)).toBe('0.8');

      // …and the column growing back restores the split the user chose.
      rerender({h: 1000});
      expect(result.current.editorHeight).toBe(800);
    });

    it('bounds the split by the pixel floors once the column is measured, and by the hard bounds before', () => {
      // An unmeasured column has no pixel floors to express, and dividing by it
      // would put Infinity in an aria-value attribute.
      expect(splitBounds(0)).toEqual({min: 0.05, max: 0.95});
      const {min, max} = splitBounds(1000);
      expect(Math.round(min * 1000)).toBe(MIN_EDITOR_HEIGHT);
      expect(Math.round(max * 1000)).toBe(1000 - MIN_RESULTS_HEIGHT - EDITOR_SPLIT_DIVIDER_HEIGHT);
      expect(EDITOR_SPLIT_KEY_STEP).toBeGreaterThan(0);
    });
  });
});

describe('the retired layout presets', () => {
  // A removal's risk is what stops being checked, so this enumerates the
  // population rather than sampling it: the directory listing, and the two
  // modules' real export sets.
  it('leaves no file, and no export, behind', async () => {
    const files = Object.keys(import.meta.glob('./*.{ts,tsx}'));
    expect(files).not.toContain('./EditorLayoutControl.tsx');
    expect(files).not.toContain('./useEditorLayout.ts');
    // The glob is only evidence if it can see the files that ARE there.
    expect(files).toContain('./useEditorSplit.ts');
    expect(files).toContain('./EditorSplitDivider.tsx');

    const retired = ['DEFAULT_LAYOUT_PRESET', 'LAYOUT_PRESET_EDITOR_FRACTION', 'QUERY_EDITOR_LAYOUT_STORAGE_PREFIX'];
    const constants = Object.keys(await import('./query.constants'));
    const barrel = Object.keys(await import('./index'));
    for (const name of retired) {
      expect(constants).not.toContain(name);
      expect(barrel).not.toContain(name);
    }
    expect(constants).toContain('QUERY_EDITOR_SPLIT_STORAGE_PREFIX');
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

    it('falls back to the default on a malformed or out-of-range stored value (FR-005)', () => {
      sessionStorage.setItem(KEY, 'lots');
      expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
      sessionStorage.setItem(KEY, '99999');
      expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
      sessionStorage.setItem(KEY, '2.5');
      expect(renderHook(() => useResultsPageSize(USER)).result.current.pageSize).toBe(DEFAULT_RESULTS_PAGE_SIZE);
    });
  });
});
