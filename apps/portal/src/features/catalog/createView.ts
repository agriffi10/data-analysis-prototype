import {sqlIdentifier} from '../../lib/sql';

/**
 * The one `CREATE OR REPLACE VIEW` this app writes.
 *
 * It lives in `features/catalog/` rather than in either caller because there are now two: the
 * Query workspace turns the editor's buffer into a view, and the Data Explorer turns the
 * exploration in front of the user into one. Written twice, the two would be free to disagree
 * about the trailing semicolon, the qualification of the name, or whether `OR REPLACE` is there
 * — and the second copy would be the one nobody tested against a real engine.
 */

/**
 * Strips trailing whitespace and semicolons so a `SELECT …;` can be embedded as a view body
 * without a stray terminator breaking the statement.
 *
 * A local copy of `features/query/`'s `stripTrailingSemicolons` would be a second definition of
 * the same rule, so the builder below owns the only call and neither caller has to remember it.
 *
 * @param sql - The statement to embed.
 * @returns The statement with trailing whitespace and semicolons removed.
 */
function stripTrailingSemicolons(sql: string): string {
  return sql.replace(/[\s;]+$/, '');
}

/**
 * Builds the statement that saves a query as a named view.
 *
 * **BOTH IDENTIFIERS ARE QUOTED, AND `database` IS THE ONE THAT MATTERS.** A view name is typed
 * into a dialog that holds it to `CATALOG_IDENTIFIER_RE` before this is called, so it arrives
 * clean. A database name does not: for a shared space it is the space's own name, and nothing
 * server-side checks that name's format — the shared-space control plane trusts the browser
 * dialog, and the SPA talks to its queue directly. A crafted space name therefore reaches a
 * member's catalog, their space list, and from there this statement, to run under their own
 * Athena credentials.
 *
 * The escaper is the **Trino** one (`lib/sql.ts`, doubles the quote), never `cpcommon.ddl`'s
 * backtick quoter: Athena parses `CREATE VIEW` with Trino, where a backtick is an error rather
 * than a quote, and AWS documents double quotes for exactly this statement. The exploration
 * renderer beside this already quotes the same value the same way — the view's BODY was safe
 * while its header was not.
 *
 * @param database - The database the view is created in.
 * @param name - The view's name.
 * @param body - The `SELECT` the view wraps; trailing semicolons are removed.
 * @returns The full statement.
 */
export function buildCreateViewSql(database: string, name: string, body: string): string {
  return `CREATE OR REPLACE VIEW ${sqlIdentifier(database)}.${sqlIdentifier(name)} AS ${stripTrailingSemicolons(body)}`;
}
