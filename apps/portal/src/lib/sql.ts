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
 * It exists because a `DROP` interpolates a database name the browser does not validate: for a
 * shared space the name is the space's own. The control plane applied no format check on its
 * create path until it took the catalog rule, and refuses only a CREATE, so a space named
 * earlier keeps any name at all. It reaches a member's space list and from there into this statement, under their
 * own Athena credentials.
 *
 * @param name - The identifier: a database, table or view name.
 * @returns The quoted, escaped identifier.
 */
export function sqlDdlIdentifier(name: string): string {
  return `\`${name.replace(/`/g, '``')}\``;
}

/**
 * The words **Trino** reserves, which must be double-quoted to be used as an identifier.
 *
 * Read from trino.io/docs/current/language/reserved.html on 2026-09-20 — 83 words, cross-checked
 * against the same page's source in the `trinodb/trino` repository, which agreed exactly. Uppercase
 * throughout, so a caller compares an uppercased candidate.
 *
 * **Nothing quotes from this list alone**: the engine is Athena, not Trino, and
 * {@link ATHENA_RESERVED_KEYWORDS} is what callers consult. This one is kept separate so its
 * provenance stays checkable against a single vendor page.
 */
export const TRINO_RESERVED_KEYWORDS: ReadonlySet<string> = new Set([
  'ALTER',
  'AND',
  'AS',
  'AUTO',
  'BETWEEN',
  'BY',
  'CASE',
  'CAST',
  'CONSTRAINT',
  'CREATE',
  'CROSS',
  'CUBE',
  'CURRENT_CATALOG',
  'CURRENT_DATE',
  'CURRENT_PATH',
  'CURRENT_ROLE',
  'CURRENT_SCHEMA',
  'CURRENT_TIME',
  'CURRENT_TIMESTAMP',
  'CURRENT_USER',
  'DEALLOCATE',
  'DELETE',
  'DESCRIBE',
  'DISTINCT',
  'DROP',
  'ELSE',
  'END',
  'ESCAPE',
  'EXCEPT',
  'EXISTS',
  'EXTRACT',
  'FALSE',
  'FOR',
  'FROM',
  'FULL',
  'GROUP',
  'GROUPING',
  'HAVING',
  'IN',
  'INNER',
  'INSERT',
  'INTERSECT',
  'INTO',
  'IS',
  'JOIN',
  'JSON_ARRAY',
  'JSON_EXISTS',
  'JSON_OBJECT',
  'JSON_QUERY',
  'JSON_TABLE',
  'JSON_VALUE',
  'LEFT',
  'LIKE',
  'LISTAGG',
  'LOCALTIME',
  'LOCALTIMESTAMP',
  'NATURAL',
  'NORMALIZE',
  'NOT',
  'NULL',
  'ON',
  'OR',
  'ORDER',
  'OUTER',
  'OVERLAPS',
  'PREPARE',
  'RECURSIVE',
  'RIGHT',
  'ROLLUP',
  'SELECT',
  'SKIP',
  'TABLE',
  'THEN',
  'TRIM',
  'TRUE',
  'UESCAPE',
  'UNION',
  'UNNEST',
  'USING',
  'VALUES',
  'WHEN',
  'WHERE',
  'WITH'
]);

// The four words Athena reserves in a SELECT that Trino's own page does not list, from
// docs.aws.amazon.com/athena/latest/ug/reserved-words.html ("Reserved keywords to escape in SQL
// SELECT statements"), read 2026-09-20. AWS's own example on that page escapes `first`, and `first`
// and `last` are ordinary column names in the data this portal handles, so the gap was reachable.
const ATHENA_ONLY_RESERVED_KEYWORDS = ['EXECUTE', 'FIRST', 'LAST', 'OF'];

/**
 * Every word that must be double-quoted to be an identifier in an Athena `SELECT`.
 *
 * The union of {@link TRINO_RESERVED_KEYWORDS} and the four words AWS lists that Trino's page does
 * not. **The engine is what decides**, and it is Athena: quoting from Trino's list alone left
 * `first`, `last`, `of` and `execute` inserted bare, which Athena refuses.
 *
 * A **superset is safe and a subset is not**, which is the asymmetry to keep in mind when
 * refreshing either list: quoting a name that needed no quotes is valid, so the three words Trino
 * reserves and Athena does not (`AUTO`, `CURRENT_ROLE`, `OVERLAPS`) cost nothing, while a missing
 * word means a name reaches the editor bare and the statement fails to parse. Athena's DDL list is
 * a different, larger list quoted with backticks — see {@link sqlDdlIdentifier} — and is
 * deliberately not folded in here.
 */
export const ATHENA_RESERVED_KEYWORDS: ReadonlySet<string> = new Set([
  ...TRINO_RESERVED_KEYWORDS,
  ...ATHENA_ONLY_RESERVED_KEYWORDS
]);

// A name the engine reads back as itself: it needs no quotes only when it is already lowercase,
// starts with a letter or underscore, and holds nothing but letters, digits and underscores. Not the
// same rule as `CATALOG_IDENTIFIER_RE`, which describes names this app CREATES — this one describes
// names the engine PARSES, and the two are not interchangeable in either direction.
const BARE_IDENTIFIER_RE = /^[a-z_][a-z0-9_]*$/;

/**
 * Quotes one identifier part for a Trino-dialect statement, but only when the part needs it.
 *
 * What the query editor's autocomplete inserts. An uppercase name is always quoted, because an
 * unquoted `ID` folds to `id` and would name a different column; a reserved word is always quoted,
 * because unquoted it is a keyword.
 *
 * This is a double-quote rule and belongs nowhere near Hive DDL — see {@link sqlDdlIdentifier}. A
 * part quoted here and pasted into a `DROP TABLE` is an error, not a silent mismatch, which is the
 * one mercy of that pair.
 *
 * @param part - One identifier part: a database, table or column name, unquoted.
 * @returns The part unchanged, or double-quoted through {@link sqlIdentifier}.
 */
export function quoteIdentifierIfNeeded(part: string): string {
  return identifierNeedsQuoting(part) ? sqlIdentifier(part) : part;
}

/**
 * Whether an identifier part parses only when quoted: an uppercase or otherwise non-bare name,
 * or a reserved word. The quote character is the caller's, because it depends on the dialect.
 *
 * @param part - One identifier part, unquoted.
 * @returns True when the part must be quoted to name what it says.
 */
export function identifierNeedsQuoting(part: string): boolean {
  return !BARE_IDENTIFIER_RE.test(part) || ATHENA_RESERVED_KEYWORDS.has(part.toUpperCase());
}
