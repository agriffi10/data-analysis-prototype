// SQL-statement classification helpers for the query workspace.

// Strip leading whitespace and SQL comments (-- line and /* block */) so callers
// can inspect the first real keyword. The editor pre-fills a `-- …` comment, so
// without this a DDL statement written under it wouldn't be detected as
// schema-changing and the schema browser wouldn't refresh.
function stripLeadingSqlComments(sql: string): string {
  let s = sql;
  for (;;) {
    const next = s
      .replace(/^\s+/, '')
      .replace(/^--[^\n]*\n?/, '')
      .replace(/^\/\*[\s\S]*?\*\//, '');
    if (next === s) return s;
    s = next;
  }
}

/**
 * Compares two SQL strings for the saved-query "dirty" marker, ignoring
 * cosmetic differences — CRLF vs LF and leading/trailing whitespace (the
 * editor commonly appends a trailing newline). Internal whitespace is left
 * intact so a genuine edit still registers.
 */
export function sameSql(a: string, b: string): boolean {
  const normalize = (s: string) => s.replace(/\r\n/g, '\n').trim();
  return normalize(a) === normalize(b);
}

/**
 * Strips trailing whitespace and semicolons so a user's `SELECT …;` can be
 * embedded as a view body (`CREATE OR REPLACE VIEW … AS <sql>`) without a
 * stray terminating semicolon breaking the statement.
 */
export function stripTrailingSemicolons(sql: string): string {
  return sql.replace(/[\s;]+$/, '');
}

/**
 * True for a statement that changes the catalog (schema browser refreshes
 * after it succeeds). CTAS is covered by the CREATE TABLE branch. Leading
 * comments/whitespace are skipped so DDL under the editor's pre-filled
 * comment is still detected.
 */
export function isSchemaChangingSql(sql: string): boolean {
  return /^(create|drop|alter)\s+(or\s+replace\s+)?(external\s+|temporary\s+)?(table|view)\b/i.test(
    stripLeadingSqlComments(sql)
  );
}

// Matches a fully-qualified base table `database.table` right after FROM or JOIN.
// CTE names and aliases are referenced unqualified (no dot) so they don't match;
// only the `db` capture group is used.
const QUALIFIED_BASE_TABLE = /\b(?:from|join)\s+([a-z_][a-z0-9_]*)\s*\.\s*[a-z_][a-z0-9_]*/gi;

// The fully-qualified `database.` right after TABLE/VIEW in a DDL statement
// (optionally through IF [NOT] EXISTS), e.g. CREATE EXTERNAL TABLE db.t / DROP
// VIEW db.v / ALTER TABLE db.t. Only the `db` capture group is used.
const DDL_QUALIFIED_TARGET = /\b(?:table|view)\s+(?:if\s+(?:not\s+)?exists\s+)?([a-z_][a-z0-9_]*)\s*\./i;

/**
 * The database a schema-changing statement targets, taken from its
 * fully-qualified `database.object` (SPEC-077 — there's no active database to
 * assume). Returns null when the statement isn't schema-changing or its target
 * isn't database-qualified. Used to refresh the right database's schema after a
 * user-typed DDL run succeeds.
 */
export function schemaChangingDatabase(sql: string): string | null {
  if (!isSchemaChangingSql(sql)) return null;
  const match = stripLeadingSqlComments(sql).match(DDL_QUALIFIED_TARGET);
  return match ? match[1].toLowerCase() : null;
}

export type ViewTarget = {database: string} | {error: string};

/**
 * Derives the target database for a "Create view" from the view body itself
 * (SPEC-077 FR-008): the single database of the fully-qualified base tables the
 * body selects from. Views generally don't span databases, so exactly one is
 * expected. Returns `{error}` (never a silent pick) when the body qualifies
 * tables from more than one database, or has no fully-qualified base table.
 */
export function deriveViewTargetDatabase(body: string): ViewTarget {
  const databases = new Set<string>();
  for (const match of body.matchAll(QUALIFIED_BASE_TABLE)) {
    databases.add(match[1].toLowerCase());
  }
  if (databases.size === 1) return {database: [...databases][0]};
  if (databases.size === 0) {
    return {
      error:
        'Qualify the tables in this query with their database (e.g. mydb.orders) so the view can be created in that database.'
    };
  }
  return {
    error: 'This query references more than one database. Scope the view to a single database before creating it.'
  };
}
