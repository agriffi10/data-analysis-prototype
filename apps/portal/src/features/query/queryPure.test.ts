import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  CLAUSE_WORDS,
  deriveViewTargetDatabase,
  isResultProducingSql,
  isSchemaChangingSql,
  isTrinoStatement,
  openQuoteStart,
  resolveRunStatements,
  sameSql,
  schemaChangingDatabase,
  splitSqlStatements,
  sqlTableReferences,
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
import {createSqlCompletionProvider, scopeAt} from './sqlCompletions';
import {ATHENA_RESERVED_KEYWORDS} from '../../lib/sql';
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

  describe('sqlTableReferences (SPEC-244 FR-001)', () => {
    it('reads a single qualified reference and stops at the first clause keyword', () => {
      expect(sqlTableReferences('SELECT * FROM denapolia.order_referring ORDER BY last_name')).toEqual([
        {database: 'denapolia', table: 'order_referring', alias: null}
      ]);
      // ORDER is reserved, so `last_name` never reads as a second reference.
      expect(sqlTableReferences('SELECT * FROM s.t WHERE')).toEqual([{database: 's', table: 't', alias: null}]);
      expect(sqlTableReferences('SELECT * FROM s.t LIMIT 10')).toEqual([{database: 's', table: 't', alias: null}]);
    });

    it('reads aliases, both bare and AS, and quoted identifier parts', () => {
      expect(
        sqlTableReferences('select o.id from sales.orders o join "my space"."Line Items" as li on li.order_id = o.id')
      ).toEqual([
        {database: 'sales', table: 'orders', alias: 'o'},
        {database: 'my space', table: 'Line Items', alias: 'li'}
      ]);
      expect(sqlTableReferences('SELECT * FROM a.x, b.y yy WHERE 1=1')).toEqual([
        {database: 'a', table: 'x', alias: null},
        {database: 'b', table: 'y', alias: 'yy'}
      ]);
    });

    it('skips string literals and comments, so a FROM inside one names nothing', () => {
      expect(sqlTableReferences("SELECT 'FROM fake.table' AS s -- JOIN c.d\nFROM real.t")).toEqual([
        {database: 'real', table: 't', alias: null}
      ]);
    });

    it('reads a WITH body and an outer join, and returns the unqualified CTE name unresolved', () => {
      expect(sqlTableReferences('WITH w AS (SELECT * FROM s.t) SELECT * FROM w LEFT OUTER JOIN s.u ON true')).toEqual([
        {database: 's', table: 't', alias: null},
        {database: null, table: 'w', alias: null},
        {database: 's', table: 'u', alias: null}
      ]);
    });

    it('treats a subquery as no reference and reads the references inside it', () => {
      expect(sqlTableReferences('SELECT * FROM (SELECT o.a, o.b FROM s.t o) sub')).toEqual([
        {database: 's', table: 't', alias: 'o'}
      ]);
      // A `(` where a table would go is read as a subquery, so a parenthesised relation names
      // nothing — the narrower list the rule is chosen for.
      expect(sqlTableReferences('SELECT * FROM (a.x) y')).toEqual([]);
    });

    it('reads an expression-level FROM too, and a three-part name as its first two', () => {
      // Both are known limits of scanning keywords instead of parsing: the phantom resolves to
      // nothing, and the truncated name falls back to offering the whole catalog.
      expect(sqlTableReferences('SELECT EXTRACT(YEAR FROM order_date) FROM sales.orders')).toEqual([
        {database: null, table: 'order_date', alias: null},
        {database: 'sales', table: 'orders', alias: null}
      ]);
      expect(sqlTableReferences('SELECT * FROM awsdatacatalog.sales.orders')).toEqual([
        {database: 'awsdatacatalog', table: 'sales', alias: null}
      ]);
    });

    it('closes the list on a `)` that drops below the depth it opened at', () => {
      // Mid-typing with unbalanced brackets is the guard's only reachable difference: the `)` takes
      // the depth below the list's own, so what follows is no longer a FROM list. The well-formed
      // half of the same rule is the WITH case above, which DOES return its reference — without it
      // this assertion would pass against a scanner that found nothing anywhere.
      expect(sqlTableReferences('FROM)s.t t')).toEqual([]);
    });

    it('does not read a column-alias list’s comma as a reference separator', () => {
      expect(sqlTableReferences('SELECT * FROM s.t AS x (a, b)')).toEqual([{database: 's', table: 't', alias: 'x'}]);
    });

    it('refuses a keyword standing where a table would, and a comma after a join condition', () => {
      expect(sqlTableReferences('SELECT * FROM s.t CROSS JOIN UNNEST(t.arr) AS u(x)')).toEqual([
        {database: 's', table: 't', alias: null}
      ]);
      expect(sqlTableReferences('FROM a.x JOIN b.y ON a.k = b.k, c.z')).toEqual([
        {database: 'a', table: 'x', alias: null},
        {database: 'b', table: 'y', alias: null}
      ]);
    });
  });

  describe('isTrinoStatement (SPEC-244 FR-005)', () => {
    it('is true for the DML statements, for CREATE [OR REPLACE] VIEW, and for a CTAS', () => {
      for (const sql of [
        'SELECT 1',
        'with x as (select 1) select * from x',
        'VALUES (1)',
        'INSERT INTO s.t VALUES (1)',
        'EXPLAIN SELECT 1',
        '-- note\nCREATE VIEW s.v AS SELECT 1',
        'create or replace view s.v as select 1',
        // A CTAS is Trino throughout — its body is DML and its head's property syntax is Trino's.
        'CREATE TABLE s.t AS SELECT 1',
        "create table s.t with (format = 'PARQUET') as select 1",
        'CREATE TABLE s.t AS WITH x AS (SELECT 1) SELECT * FROM x'
      ]) {
        expect(isTrinoStatement(sql), sql).toBe(true);
      }
    });

    it('is false for the Hive DDL, so those keep the bare insert', () => {
      for (const sql of [
        'CREATE EXTERNAL TABLE s.t (a int)',
        // `STORED AS PARQUET` is an AS that opens no query — the next-word check is what sees that.
        "CREATE EXTERNAL TABLE s.t (a int) STORED AS PARQUET LOCATION 's3://b/p/'",
        'CREATE TABLE s.t (a int)',
        'DROP TABLE s.t',
        'ALTER TABLE s.t ADD COLUMNS (b int)',
        'SHOW TABLES IN s',
        ''
      ]) {
        expect(isTrinoStatement(sql), sql).toBe(false);
      }
    });

    it('reads only an AS outside brackets as the one that opens a CTAS body', () => {
      // The positive control comes first: a property list closes, and the AS AFTER it is the real
      // one — without that line this test would pass against a scan that found no AS anywhere.
      expect(isTrinoStatement("CREATE TABLE s.t WITH (sorted_by = ARRAY['a']) AS SELECT 1")).toBe(true);
      // An AS inside a bracketed list is a cast or a property, never the body's.
      expect(isTrinoStatement('CREATE TABLE s.t (x varchar) WITH (comment = cast(y AS TABLE))')).toBe(false);
      expect(isTrinoStatement('CREATE TABLE s.t (a int) WITH (p = (SELECT 1 AS SELECT))')).toBe(false);
    });

    it('answers false for a CTAS whose AS SELECT has not been typed yet', () => {
      // Before the body exists it is indistinguishable from a Hive CREATE TABLE, so the bare insert
      // is the only honest answer; the classification flips once `AS SELECT` lands.
      expect(isTrinoStatement('CREATE TABLE s.t ')).toBe(false);
      expect(isTrinoStatement('CREATE TABLE s.t AS ')).toBe(false);
    });
  });

  describe('openQuoteStart (SPEC-244 FR-005)', () => {
    it('reports the offset inside an unclosed double quote', () => {
      expect(openQuoteStart('SELECT "Last Na')).toBe(8);
      expect(openQuoteStart('SELECT "a""b')).toBe(8);
      expect(openQuoteStart('SELECT "x", "y')).toBe(13);
    });

    it('reports null once the quote closes — including on the last character', () => {
      // The quote scan ends at the buffer's length for BOTH an unterminated quote and one closing
      // on the final character, so a length check alone would overwrite a finished identifier here.
      expect(openQuoteStart('SELECT "Last Name"')).toBeNull();
      expect(openQuoteStart('SELECT ""')).toBeNull();
      expect(openQuoteStart('SELECT """')).toBe(8);
      expect(openQuoteStart('SELECT ')).toBeNull();
    });

    it('reports null inside a string literal, a backtick name or a comment', () => {
      expect(openQuoteStart('SELECT \'a " b')).toBeNull();
      expect(openQuoteStart('SELECT `a " b')).toBeNull();
      expect(openQuoteStart('SELECT 1 -- a " b')).toBeNull();
      expect(openQuoteStart('SELECT 1 /* a " b')).toBeNull();
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

  // Minimal fake Monaco surface the provider factory touches: just the kind enum. No editor
  // runtime involved.
  const fakeMonaco = {
    languages: {
      CompletionItemKind: {Field: 3, Struct: 5, Interface: 7}
    }
  } as unknown as Parameters<typeof createSqlCompletionProvider>[0];

  type ProvideCompletions = NonNullable<ReturnType<typeof createSqlCompletionProvider>['provideCompletionItems']>;
  type Suggestion = {
    label: string;
    insertText: string;
    kind: number;
    detail: string;
    range: {startLineNumber: number; endLineNumber: number; startColumn: number; endColumn: number};
  };

  // The editor's model, reduced to what the provider reads: the whole buffer, the cursor as an
  // offset, the word characters immediately before it (which is what Monaco's
  // getWordUntilPosition returns — the word truncated at the cursor), and one offset→position
  // conversion. `accept` applies a suggestion the way the editor would, so a test can assert the
  // text the user is left with rather than an insertText in isolation.
  function editorAt(buffer: string, cursorOffset: number) {
    const positionOf = (offset: number) => {
      const before = buffer.slice(0, offset);
      return {lineNumber: before.split('\n').length, column: offset - before.lastIndexOf('\n')};
    };
    const offsetOf = ({lineNumber, column}: {lineNumber: number; column: number}) => {
      const lines = buffer.split('\n');
      let offset = 0;
      for (let i = 0; i < lineNumber - 1; i += 1) offset += lines[i].length + 1;
      return offset + column - 1;
    };
    const word = /[A-Za-z0-9_$]*$/.exec(buffer.slice(0, cursorOffset))?.[0] ?? '';
    const position = positionOf(cursorOffset);
    const model = {
      getValue: () => buffer,
      getOffsetAt: () => cursorOffset,
      getPositionAt: positionOf,
      getWordUntilPosition: () => ({
        word,
        startColumn: position.column - word.length,
        endColumn: position.column
      })
    } as unknown as Parameters<ProvideCompletions>[0];

    const suggest = (schemas: DatabaseSchema[] | undefined) => {
      const provider = createSqlCompletionProvider(fakeMonaco, {current: schemas});
      const result = provider.provideCompletionItems?.(
        model,
        position as unknown as Parameters<ProvideCompletions>[1],
        {} as never,
        {} as never
      );
      return (result as unknown as {suggestions: Suggestion[]}).suggestions;
    };

    const accept = (suggestion: Suggestion) =>
      buffer.slice(0, offsetOf({lineNumber: suggestion.range.startLineNumber, column: suggestion.range.startColumn})) +
      suggestion.insertText +
      buffer.slice(offsetOf({lineNumber: suggestion.range.endLineNumber, column: suggestion.range.endColumn}));

    return {suggest, accept};
  }

  const labelsOfKind = (suggestions: Suggestion[], kind: number) =>
    suggestions.filter((s) => s.kind === kind).map((s) => s.label);
  const COLUMN = 3;
  const TABLE = 5;
  const VIEW = 7;

  const column = (name: string, type: string) => ({name, type});
  const orderReferring: GlueTableSummary = {
    name: 'order_referring',
    tableType: 'EXTERNAL_TABLE',
    columns: [column('last_name', 'varchar'), column('npi', 'bigint')]
  };
  // The tester's own schema shape: the table they queried, and one other they can also reach.
  const scopeSchemas: DatabaseSchema[] = [
    {database: 'denapolia', tables: [orderReferring]},
    {
      database: 'other',
      tables: [{name: 'claims', tableType: 'EXTERNAL_TABLE', columns: [column('claim_id', 'varchar')]}]
    }
  ];
  const salesSchemas: DatabaseSchema[] = [
    {
      database: 'sales',
      tables: [
        {name: 'orders', tableType: 'EXTERNAL_TABLE', columns: [column('id', 'bigint'), column('placed_on', 'date')]},
        {name: 'items', tableType: 'EXTERNAL_TABLE', columns: [column('id', 'varchar'), column('name', 'varchar')]},
        {name: 'orders_summary', tableType: 'VIRTUAL_VIEW', columns: [column('total', 'double')]}
      ]
    }
  ];

  describe('the whole-catalogue suggestions', () => {
    it('returns one fully-qualified item per table and view, kinded and labelled', () => {
      const suggestions = editorAt('', 0).suggest([alice]);
      expect(suggestions.find((s) => s.label === 'alice.orders')).toMatchObject({
        insertText: 'alice.orders',
        kind: TABLE,
        detail: 'table · alice'
      });
      expect(suggestions.find((s) => s.label === 'alice.orders_summary')).toMatchObject({
        insertText: 'alice.orders_summary',
        kind: VIEW,
        detail: 'view · alice'
      });
    });

    it('emits one column item per column with its type and qualified table as detail', () => {
      const suggestions = editorAt('', 0).suggest([{database: 'alice', tables: [orders]}]);
      expect(suggestions.filter((s) => s.kind === COLUMN)).toMatchObject([
        {label: 'id', insertText: 'id', detail: 'bigint · alice.orders'},
        {label: 'total', insertText: 'total', detail: 'double · alice.orders'}
      ]);
    });

    it('de-duplicates column names across tables and databases (keeps first declaration)', () => {
      const suggestions = editorAt('', 0).suggest([
        {database: 'alice', tables: [orders]},
        {database: 'bob', tables: [ordersView]}
      ]);
      const totals = suggestions.filter((s) => s.kind === COLUMN && s.label === 'total');
      expect(totals).toHaveLength(1);
      expect(totals[0].detail).toBe('double · alice.orders');
    });
  });

  describe('scopeAt (SPEC-244 FR-002)', () => {
    it('resolves the statement’s tables case-insensitively and nothing else', () => {
      const buffer = 'SELECT * FROM DENAPOLIA.Order_Referring ORDER BY ';
      const scoped = scopeAt(buffer, buffer.length, scopeSchemas);
      expect(scoped.map((s) => `${s.database}.${s.table.name}`)).toEqual(['denapolia.order_referring']);
      expect(scoped[0].aliases).toEqual([]);
    });

    it('follows the cursor across statements, including into the whitespace after one', () => {
      const buffer = 'SELECT * FROM denapolia.order_referring;\n\nSELECT * FROM other.claims;\n';
      const inSecond = buffer.indexOf('other.claims') + 2;
      expect(scopeAt(buffer, inSecond, scopeSchemas).map((s) => s.table.name)).toEqual(['claims']);
      const afterFirst = buffer.indexOf(';') + 2;
      expect(scopeAt(buffer, afterFirst, scopeSchemas).map((s) => s.table.name)).toEqual(['order_referring']);
    });

    it('resolves neither an unknown database, an unqualified name, nor the wrong database', () => {
      // `other.order_referring` names a real table under the wrong database: the database half of
      // the match is what refuses it.
      const buffer = 'SELECT * FROM nosuch.table_x, orders, other.order_referring WHERE ';
      // All three ARE read as references — the empty scope is resolution failing, not the scan.
      expect(sqlTableReferences(buffer)).toEqual([
        {database: 'nosuch', table: 'table_x', alias: null},
        {database: null, table: 'orders', alias: null},
        {database: 'other', table: 'order_referring', alias: null}
      ]);
      expect(scopeAt(buffer, buffer.length, scopeSchemas)).toEqual([]);
    });
  });

  describe('createSqlCompletionProvider — scoped columns (SPEC-244 FR-003)', () => {
    it('offers only the resolved table’s columns, and still every table', () => {
      const buffer = 'SELECT * FROM DENAPOLIA.Order_Referring ORDER BY ';
      const suggestions = editorAt(buffer, buffer.length).suggest(scopeSchemas);
      expect(labelsOfKind(suggestions, COLUMN)).toEqual(['last_name', 'npi']);
      expect(labelsOfKind(suggestions, TABLE)).toContain('other.claims');
    });

    it('lists every resolved table a de-duplicated column came from, with its type there', () => {
      const buffer = 'select * from sales.orders o join sales.items i on true where ';
      const suggestions = editorAt(buffer, buffer.length).suggest(salesSchemas);
      const ids = suggestions.filter((s) => s.label === 'id');
      expect(ids).toHaveLength(1);
      expect(ids[0].detail).toBe('bigint · sales.orders; varchar · sales.items');
    });

    it('falls back to every column while the statement has no FROM yet', () => {
      const suggestions = editorAt('SELECT ', 7).suggest(scopeSchemas);
      expect(labelsOfKind(suggestions, COLUMN)).toEqual(['last_name', 'npi', 'claim_id']);
    });
  });

  describe('createSqlCompletionProvider — after a qualifier and a dot (SPEC-244 FR-004)', () => {
    it('offers one alias’s table columns', () => {
      const buffer = 'select o. from sales.orders o join sales.items i on true';
      const suggestions = editorAt(buffer, 9).suggest(salesSchemas);
      expect(suggestions.map((s) => s.label)).toEqual(['id', 'placed_on']);
    });

    it('declares the dot as a trigger, without which the popup never opens on it', () => {
      expect(createSqlCompletionProvider(fakeMonaco, {current: salesSchemas}).triggerCharacters).toEqual(['.']);
    });

    it('offers a resolved table’s columns when the qualifier is its name', () => {
      const buffer = 'select items.na from sales.items';
      expect(
        editorAt(buffer, 13)
          .suggest(salesSchemas)
          .map((s) => s.label)
      ).toEqual(['id', 'name']);
    });

    it('prefers an alias over a table of the same name', () => {
      const buffer = 'select b. from s.a b join s.b c';
      const schemas: DatabaseSchema[] = [
        {
          database: 's',
          tables: [
            {name: 'a', tableType: 'EXTERNAL_TABLE', columns: [column('from_a', 'varchar')]},
            {name: 'b', tableType: 'EXTERNAL_TABLE', columns: [column('from_b', 'varchar')]}
          ]
        }
      ];
      expect(
        editorAt(buffer, 9)
          .suggest(schemas)
          .map((s) => s.label)
      ).toEqual(['from_a']);
    });

    it('falls through to the statement’s scope when the qualifier matches nothing', () => {
      const buffer = 'select x. from sales.orders o';
      const suggestions = editorAt(buffer, 9).suggest(salesSchemas);
      expect(labelsOfKind(suggestions, COLUMN)).toEqual(['id', 'placed_on']);
      expect(labelsOfKind(suggestions, TABLE)).toEqual(['sales.orders', 'sales.items']);
    });

    it('reads no qualifier from a bare name with no dot after it', () => {
      // Without the dot, `sales` is a word the user is typing, not a qualifier — the tables stay
      // fully qualified, since inserting a bare `orders` there would leave `select sales orders`.
      const buffer = 'select sales ';
      const suggestions = editorAt(buffer, buffer.length).suggest(salesSchemas);
      expect(labelsOfKind(suggestions, TABLE)).toEqual(['sales.orders', 'sales.items']);
    });

    it('offers a database’s tables after its name, and does not repeat the database', () => {
      const buffer = 'select * from sales.';
      const {suggest, accept} = editorAt(buffer, buffer.length);
      const suggestions = suggest(salesSchemas);
      expect(labelsOfKind(suggestions, TABLE)).toEqual(['orders', 'items']);
      expect(labelsOfKind(suggestions, VIEW)).toEqual(['orders_summary']);
      expect(labelsOfKind(suggestions, COLUMN)).toEqual([]);
      expect(accept(suggestions.find((s) => s.label === 'orders') as Suggestion)).toBe('select * from sales.orders');
    });
  });

  describe('createSqlCompletionProvider — quoting (SPEC-244 FR-005)', () => {
    // Names a refresh, a view alias or a shared space's own name can carry into the editor.
    const quirky: DatabaseSchema[] = [
      {
        database: 'my space',
        tables: [
          {
            name: 'orders',
            tableType: 'EXTERNAL_TABLE',
            columns: [
              column('last_name', 'varchar'),
              column('Last Name', 'varchar'),
              column('order', 'varchar'),
              column('NPI', 'bigint'),
              column('2024_total', 'double'),
              column('a"b', 'varchar')
            ]
          }
        ]
      },
      {database: 'sales', tables: [{name: 'order', tableType: 'EXTERNAL_TABLE', columns: []}]}
    ];

    it('quotes only the parts a Trino statement needs quoted', () => {
      const suggestions = editorAt('SELECT ', 7).suggest(quirky);
      const insertFor = (label: string) => suggestions.find((s) => s.label === label)?.insertText;
      expect(insertFor('last_name')).toBe('last_name');
      expect(insertFor('Last Name')).toBe('"Last Name"');
      expect(insertFor('order')).toBe('"order"');
      // Bare-identifier-shaped and still quoted: unquoted, Athena folds it to `npi`.
      expect(insertFor('NPI')).toBe('"NPI"');
      expect(insertFor('2024_total')).toBe('"2024_total"');
      expect(insertFor('a"b')).toBe('"a""b"');
    });

    it('quotes a table part by part, leaving the label bare', () => {
      const suggestions = editorAt('SELECT * FROM ', 14).suggest(quirky);
      const table = suggestions.find((s) => s.label === 'my space.orders');
      expect(table?.insertText).toBe('"my space".orders');
    });

    it('leaves a Hive DDL statement’s insert bare, reserved word and all', () => {
      const suggestions = editorAt('DROP TABLE ', 11).suggest(quirky);
      expect(suggestions.find((s) => s.label === 'sales.order')?.insertText).toBe('sales.order');
      expect(suggestions.find((s) => s.label === 'Last Name')?.insertText).toBe('Last Name');
    });

    it('quotes inside a CTAS, whose bare insert changed the column silently', () => {
      // A bare `Last Name` here becomes column `Last` aliased `Name`, and a bare `2024_total` a
      // number — and a CTAS WRITES both into the new table, so this was the one silent exclusion.
      const buffer = 'CREATE TABLE my space.copy AS SELECT  FROM "my space".orders';
      const {suggest} = editorAt(buffer, buffer.indexOf('SELECT ') + 7);
      const suggestions = suggest(quirky);
      const insertFor = (label: string) => suggestions.find((s) => s.label === label)?.insertText;
      expect(insertFor('Last Name')).toBe('"Last Name"');
      expect(insertFor('2024_total')).toBe('"2024_total"');
      expect(insertFor('last_name')).toBe('last_name');
    });

    it('completes inside the user’s own open quote, closing it', () => {
      const {suggest, accept} = editorAt('SELECT "Last Na', 15);
      const suggestions = suggest(quirky);
      expect(accept(suggestions.find((s) => s.label === 'Last Name') as Suggestion)).toBe('SELECT "Last Name"');
    });

    it('adds no second closing quote when the editor already inserted one', () => {
      // The gesture the SQL language's autoClosingPairs actually produces: typing `"` inserts its
      // pair, so the cursor sits BEFORE a closing quote rather than at the end of an open one.
      const {suggest, accept} = editorAt('SELECT "Las"', 11);
      const suggestions = suggest(quirky);
      expect(accept(suggestions.find((s) => s.label === 'Last Name') as Suggestion)).toBe('SELECT "Last Name"');
    });

    it('offers columns but no table inside an open quote, and doubles an inner quote', () => {
      const {suggest, accept} = editorAt('SELECT "a', 9);
      const suggestions = suggest(quirky);
      expect(labelsOfKind(suggestions, TABLE)).toEqual([]);
      expect(labelsOfKind(suggestions, VIEW)).toEqual([]);
      expect(suggestions.map((s) => s.label)).toContain('a"b');
      expect(accept(suggestions.find((s) => s.label === 'a"b') as Suggestion)).toBe('SELECT "a""b"');
    });

    it('takes the plain word gesture when the open quote is on an earlier line', () => {
      // Monaco discards a range starting on another line, so a stray quote must not cost every
      // suggestion — it falls back to replacing the word at the cursor.
      const buffer = 'SELECT "stray,\n  last';
      const suggestions = editorAt(buffer, buffer.length).suggest(quirky);
      const one = suggestions.find((s) => s.label === 'last_name') as Suggestion;
      expect(one.range).toEqual({startLineNumber: 2, endLineNumber: 2, startColumn: 3, endColumn: 7});
      expect(labelsOfKind(suggestions, TABLE)).toContain('my space.orders');
    });

    it('keeps the reserved words uppercase and disjoint from the clause words', () => {
      // The four presences are the positive control: a `for…of` over an empty set passes
      // vacuously. The lists' own sizes and provenance are pinned in `lib/sql.test.ts`.
      for (const word of ['SELECT', 'ORDER', 'GROUP', 'JSON_TABLE']) {
        expect(ATHENA_RESERVED_KEYWORDS.has(word), word).toBe(true);
      }
      // Disjoint, not contradictory: a FROM list closes on EITHER a reserved word or a clause
      // word, and the two sets never overlap — `ORDER` closes it by the first mechanism and
      // `LIMIT`, which neither vendor reserves, by the second.
      for (const word of ATHENA_RESERVED_KEYWORDS) {
        expect(word, word).toBe(word.toUpperCase());
        expect(CLAUSE_WORDS.has(word), word).toBe(false);
      }
      expect(CLAUSE_WORDS.size).toBe(7);
    });
  });

  describe('createSqlCompletionProvider', () => {
    it('maps descriptors onto Monaco items with a word-replacement range', () => {
      const suggestions = editorAt('or', 2).suggest([alice]);

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
