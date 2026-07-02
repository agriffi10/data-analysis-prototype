import {describe, it, expect} from 'vitest';
import {isSchemaChangingSql, sameSql} from './query.sql';

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
