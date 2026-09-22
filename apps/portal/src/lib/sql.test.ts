import {describe, expect, it} from 'vitest';
import {
  ATHENA_RESERVED_KEYWORDS,
  TRINO_RESERVED_KEYWORDS,
  quoteIdentifierIfNeeded,
  sqlDdlIdentifier,
  sqlIdentifier,
  sqlLiteral
} from './sql';
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

  it('doubles an embedded backtick, so a crafted database name cannot close the quote', () => {
    // A `DROP` interpolates a shared-space database name the control plane format-checked
    // nowhere until the create path took the rule, so this escaper is the only thing
    // between a crafted space name and a
    // statement running under a member's own Athena credentials. The failure mode is the
    // one the register names for this pair: the wrong rule is a predicate that never
    // matches, and nothing goes red.
    expect(sqlDdlIdentifier('a`b')).toBe('`a``b`');
    expect(sqlDdlIdentifier('ok')).toBe('`ok`');
    expect(sqlDdlIdentifier('a`; DROP TABLE x; --')).toBe('`a``; DROP TABLE x; --`');
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

describe('quoteIdentifierIfNeeded (SPEC-244 FR-005)', () => {
  it('leaves a name the engine reads back as itself alone', () => {
    for (const name of ['last_name', '_private', 'a1', 'order_referring', 'npi']) {
      expect(quoteIdentifierIfNeeded(name), name).toBe(name);
    }
  });

  it('quotes an UPPERCASE name, because unquoted it folds to a different column', () => {
    // The half a corpus of spaces and punctuation never reaches: `NPI` is bare-identifier-shaped
    // and still needs quoting, since Athena folds an unquoted `NPI` to `npi`.
    expect(quoteIdentifierIfNeeded('NPI')).toBe('"NPI"');
    expect(quoteIdentifierIfNeeded('Total')).toBe('"Total"');
    expect(quoteIdentifierIfNeeded('camelCase')).toBe('"camelCase"');
  });

  it('quotes a shape the engine cannot parse bare', () => {
    expect(quoteIdentifierIfNeeded('Last Name')).toBe('"Last Name"');
    expect(quoteIdentifierIfNeeded('2024_total')).toBe('"2024_total"');
    expect(quoteIdentifierIfNeeded('total_$')).toBe('"total_$"');
    expect(quoteIdentifierIfNeeded('a-b')).toBe('"a-b"');
    expect(quoteIdentifierIfNeeded('a"b')).toBe('"a""b"');
    expect(quoteIdentifierIfNeeded('')).toBe('""');
  });

  it('quotes a reserved word in ANY case, Athena’s four included', () => {
    // The engine is Athena, not Trino: `first`, `last`, `of` and `execute` are ordinary column
    // names, absent from Trino's own page, and inserted bare they make the statement unparseable.
    for (const word of ['order', 'ORDER', 'Group', 'select', 'first', 'last', 'of', 'execute']) {
      expect(quoteIdentifierIfNeeded(word), word).toBe(`"${word}"`);
    }
  });
});

describe('the reserved-word lists (SPEC-244 FR-005)', () => {
  it('reads Trino’s page and Athena’s as two lists, the second a superset of the first', () => {
    // Both sizes are pinned so each docstring's count is a checkable fact rather than prose that
    // rots, and the four are named so swapping one for another cannot keep the count green.
    expect(TRINO_RESERVED_KEYWORDS.size).toBe(83);
    expect(ATHENA_RESERVED_KEYWORDS.size).toBe(87);
    for (const word of ['EXECUTE', 'FIRST', 'LAST', 'OF']) {
      expect(TRINO_RESERVED_KEYWORDS.has(word), word).toBe(false);
      expect(ATHENA_RESERVED_KEYWORDS.has(word), word).toBe(true);
    }
    for (const word of TRINO_RESERVED_KEYWORDS) {
      expect(ATHENA_RESERVED_KEYWORDS.has(word), word).toBe(true);
    }
  });
});
