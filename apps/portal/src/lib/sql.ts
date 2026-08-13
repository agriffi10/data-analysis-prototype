/**
 * SQL escaping for queries the BROWSER composes (SPEC-178 FR-004).
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
 * bar, which is the user's own SQL and passes through verbatim (SPEC-178 FR-005).
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
 * database, a view), and column names are not catalog-safe — SPEC-144 had to record the
 * same fact for a different reason. Validating a name and quoting one are different jobs
 * and are not interchangeable.
 *
 * @param name - The identifier: a database, table or column name.
 * @returns The quoted, escaped identifier.
 */
export function sqlIdentifier(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}
