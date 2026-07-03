import {describe, it, expect} from 'vitest';
import {deriveViewTargetDatabase, isSchemaChangingSql, sameSql, schemaChangingDatabase} from './query.sql';

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
