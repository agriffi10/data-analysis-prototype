/**
 * SQL escaping for queries the BROWSER composes.
 *
 * These live in `lib/` rather than in a feature because they are language rules, not
 * feature domain — the Data Explorer is the first caller, not the owner.
 *
 * **Two escapers, never confused.** The repo already carries this distinction on the
 * Python side and these are its TypeScript half:
 *
 * | Rule | Dialect | Escape | Where |
 * |---|---|---|---|
 * | `sqlLiteral` (here) | Trino / **DML** | double the quote (`''`) | every `SELECT` this app builds |
 * | `cpcommon.ddl.literal` | Hive / **DDL** | backslash (`\'`, `\\`) | `CREATE TABLE`, `TBLPROPERTIES`, `LOCATION` |
 *
 * Athena's two dialects fail at *query* time, not build time. Trino has no backslash
 * escape in a plain string literal — the only escape is doubling the quote — so the Hive
 * form renders a literal backslash into the value being matched. The failure mode is the
 * bad one: no error, just a predicate that silently never matches.
 */

/**
 * Renders a Trino/DML string literal: single-quoted, with embedded single quotes doubled.
 *
 * This is what every value the app quotes ON THE USER'S BEHALF goes through — a filter
 * built from a cell value, a per-column menu choice. It is NOT for the raw expression
 * bar, which is the user's own SQL and passes through verbatim.
 *
 * @param value - The raw value, straight from data. `O'Brien` is the whole hazard.
 * @returns The quoted, escaped literal, ready to concatenate.
 */
export function sqlLiteral(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/**
 * Renders a double-quoted Trino identifier, with embedded double quotes doubled.
 *
 * Column names go through this and must **not** be checked against
 * `CATALOG_IDENTIFIER_RE`: that rule describes names this app CREATES (a username, a
 * database, a view), and column names are not catalog-safe — the refresh had to record the
 * same fact for a different reason. Validating a name and quoting one are different jobs
 * and are not interchangeable.
 *
 * @param name - The identifier: a database, table or column name.
 * @returns The quoted, escaped identifier.
 */
export function sqlIdentifier(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}

/**
 * Backtick-quotes an identifier for a **DDL** statement — `DROP TABLE`, `DROP VIEW` — with any
 * embedded backtick doubled.
 *
 * The sibling of {@link sqlIdentifier} and never a substitute for it. Athena runs the two
 * halves of SQL through different parsers: DDL is Hive, where a backtick is the identifier
 * quote and a double quote is not; DML and `CREATE VIEW` are Trino, where the reverse holds.
 * Using the wrong one fails at query time, after the diff and the golden-string test have both
 * looked right — which is the failure mode the lambda layer records for the same pair.
 *
 * It exists because a `DROP` interpolates a database name that nothing validates: for a shared
 * space the name is the space's own, and the control plane applies no format check on its
 * create path. A crafted name reaches a member's space list and from there into this statement,
 * under their own Athena credentials.
 *
 * @param name - The identifier: a database, table or view name.
 * @returns The quoted, escaped identifier.
 */
export function sqlDdlIdentifier(name: string): string {
  return `\`${name.replace(/`/g, '``')}\``;
}
