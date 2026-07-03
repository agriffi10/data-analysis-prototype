import {describe, it, expect} from 'vitest';
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
