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

// A statement that changes the catalog — after it succeeds the schema browser is
// refreshed. CTAS (CREATE TABLE … AS) is covered by the CREATE TABLE branch.
// Leading comments/whitespace are skipped first so a DDL statement under the
// editor's pre-filled comment is still detected.
export function isSchemaChangingSql(sql: string): boolean {
  return /^(create|drop|alter)\s+(or\s+replace\s+)?(external\s+|temporary\s+)?(table|view)\b/i.test(
    stripLeadingSqlComments(sql),
  );
}
