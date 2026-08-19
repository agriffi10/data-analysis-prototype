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
 * The identifiers are interpolated unquoted, which is deliberate and bounded rather than an
 * omission: `database` is a catalog-safe identifier by construction — it is a username or a
 * shared-space name, both held to `CATALOG_IDENTIFIER_RE` at creation — and `name` is validated
 * against the same rule by the dialog that collects it, before this is ever called. Quoting
 * here would be the *DDL* quoter (backticks), and Athena parses `CREATE VIEW` with Trino, where
 * backticks are an error rather than a quote. The correct escape for this statement is to
 * refuse an identifier that needs one, which is what the dialog does.
 *
 * @param database - The database the view is created in.
 * @param name - The view's name, already validated as catalog-safe.
 * @param body - The `SELECT` the view wraps; trailing semicolons are removed.
 * @returns The full statement.
 */
export function buildCreateViewSql(database: string, name: string, body: string): string {
  return `CREATE OR REPLACE VIEW ${database}.${name} AS ${stripTrailingSemicolons(body)}`;
}
