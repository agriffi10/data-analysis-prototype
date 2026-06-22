// SQL-statement classification helpers for the query workspace (SPEC-034/035).

// Strip leading whitespace and SQL comments (-- line and /* block */) so callers
// can inspect the first real keyword. The editor pre-fills a `-- …` comment, so
// without this a `CREATE TABLE` written under a leading comment wouldn't be
// detected as schema-changing and the schema browser wouldn't refresh.
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

// SPEC-043 FR-008: compare two SQL strings for the saved-query "dirty" marker,
// ignoring cosmetic differences — CRLF vs LF line endings and leading/trailing
// whitespace (the editor commonly appends a trailing newline). Internal whitespace
// is left intact so a genuine edit still registers.
export function sameSql(a: string, b: string): boolean {
  const normalize = (s: string) => s.replace(/\r\n/g, '\n').trim();
  return normalize(a) === normalize(b);
}

// SPEC-048: strip trailing whitespace and semicolons so a user's `SELECT …;` can
// be embedded as a view body (`CREATE OR REPLACE VIEW … AS <sql>`) without a stray
// terminating semicolon breaking the statement.
export function stripTrailingSemicolons(sql: string): string {
  return sql.replace(/[\s;]+$/, '');
}

// A statement that changes the catalog — after it succeeds the schema browser is
// refreshed. CTAS (CREATE TABLE … AS) is covered by the CREATE TABLE branch.
// Leading comments/whitespace are skipped first so a DDL statement under the
// editor's pre-filled comment is still detected.
export function isSchemaChangingSql(sql: string): boolean {
  return /^(create|drop|alter)\s+(or\s+replace\s+)?(external\s+|temporary\s+)?(table|view)\b/i.test(
    stripLeadingSqlComments(sql),
  );
}
