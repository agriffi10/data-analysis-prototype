import {describe, expect, it} from 'vitest';
import {sqlLiteral, sqlIdentifier} from './sql';
import {CATALOG_IDENTIFIER_RE} from './catalogIdentifier';

describe('sqlLiteral (SPEC-178 FR-004)', () => {
  it('doubles an embedded single quote and does NOT backslash it', () => {
    // The whole hazard in one value: it arrives from real data via filter-by-cell-value
    // long before anyone thinks to type it.
    expect(sqlLiteral("O'Brien")).toBe("'O''Brien'");
    expect(sqlLiteral("O'Brien")).not.toContain('\\');
  });

  it('quotes an ordinary value with nothing added', () => {
    expect(sqlLiteral('alice')).toBe("'alice'");
    expect(sqlLiteral('')).toBe("''");
  });

  it('doubles EVERY quote, including adjacent and terminal ones', () => {
    expect(sqlLiteral("''")).toBe("''''''");
    expect(sqlLiteral("a'")).toBe("'a'''");
    expect(sqlLiteral("'a")).toBe("'''a'");
  });

  it('leaves a backslash alone — it is not an escape character in Trino', () => {
    // A Hive-escaped value would read `'a\\b'` and match a path that does not exist.
    expect(sqlLiteral('a\\b')).toBe("'a\\b'");
  });

  it('is NOT the Hive/DDL escaper — the two diverge on a backslash', () => {
    // The reference implementation of `cpcommon.ddl.literal`, transcribed so the
    // divergence is asserted against the other rule rather than described in a comment.
    // If someone "fixes" sqlLiteral to escape backslashes, this fails and names why.
    const hiveDdlLiteral = (value: string) => `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;

    expect(hiveDdlLiteral('a\\b')).toBe("'a\\\\b'");
    expect(sqlLiteral('a\\b')).not.toBe(hiveDdlLiteral('a\\b'));
    expect(sqlLiteral("O'Brien")).not.toBe(hiveDdlLiteral("O'Brien"));

    // And the reason they may never be swapped: an ordinary value renders identically
    // through both, so a conflated escaper passes every test built from ordinary data.
    expect(sqlLiteral('alice')).toBe(hiveDdlLiteral('alice'));
  });
});

describe('sqlIdentifier (SPEC-178 FR-004)', () => {
  it('double-quotes and doubles an embedded double quote', () => {
    expect(sqlIdentifier('a"b')).toBe('"a""b"');
    expect(sqlIdentifier('orders')).toBe('"orders"');
  });

  it('quotes names CATALOG_IDENTIFIER_RE would reject — a column name is not catalog-safe', () => {
    // AC: column names must NOT be validated against the catalog rule. That rule
    // describes names this app CREATES; these are names it READS out of Glue, and a
    // validator here would refuse legitimate columns rather than quote them.
    const realColumnNames = ['Order Date', 'total_$', 'UPPER', '2024', 'a-b'];
    for (const name of realColumnNames) {
      expect(CATALOG_IDENTIFIER_RE.test(name)).toBe(false);
      expect(sqlIdentifier(name)).toBe(`"${name}"`);
    }
  });

  it('does not touch a single quote — that is the literal escaper’s job', () => {
    expect(sqlIdentifier("O'Brien")).toBe('"O\'Brien"');
  });
});
