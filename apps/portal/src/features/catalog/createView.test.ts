import {describe, expect, it} from 'vitest';
import {buildCreateViewSql} from './createView';

/**
 * The one `CREATE OR REPLACE VIEW` this app writes, now that two surfaces write one.
 *
 * The identifier that matters is the DATABASE. A view name is typed into a dialog that holds it
 * to the catalog-safe rule; a shared space's name was held to nothing the browser cannot bypass,
 * since the SPA talks to its queue directly. The control plane checks a CREATE and only a
 * create, and checked nothing before, so a space named earlier still carries anything.
 */
describe('buildCreateViewSql', () => {
  it('quotes both identifiers with the TRINO escaper, not the DDL one', () => {
    // Double quotes, never backticks: Athena parses CREATE VIEW with Trino, where a backtick is
    // an error rather than a quote — the wrong quoter fails at query time, after the diff and
    // the golden-string test both looked right.
    const sql = buildCreateViewSql('alice', 'monthly', 'SELECT 1');
    expect(sql).toBe('CREATE OR REPLACE VIEW "alice"."monthly" AS SELECT 1');
    expect(sql).not.toContain('`');
  });

  it('escapes a database name that tries to break out of its quotes', () => {
    // A crafted shared-space name reaches a member's space list and from there this statement,
    // to run under their own Athena credentials. Doubling the quote is what makes the name a
    // name rather than the end of one.
    const sql = buildCreateViewSql('ev"il', 'v', 'SELECT 1');
    expect(sql).toBe('CREATE OR REPLACE VIEW "ev""il"."v" AS SELECT 1');
  });

  it('strips a trailing semicolon so the body embeds as a body', () => {
    expect(buildCreateViewSql('alice', 'v', 'SELECT 1;  \n')).toBe('CREATE OR REPLACE VIEW "alice"."v" AS SELECT 1');
  });

  it('leaves a semicolon INSIDE the body alone', () => {
    // Only the trailing run is stripped — a semicolon inside a string literal is data.
    expect(buildCreateViewSql('alice', 'v', "SELECT ';' AS x")).toBe(
      'CREATE OR REPLACE VIEW "alice"."v" AS SELECT \';\' AS x'
    );
  });
});
