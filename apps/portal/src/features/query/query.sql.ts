// SQL-statement classification + splitting helpers for the query workspace.

import type {ParsedStatement} from './query.types';

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
  // safe-regex flags the star height (\s+ inside an optional group), not measured
  // backtracking. Each optional group is anchored by a literal (`or`, `replace`,
  // `external`), so a failing alternative is rejected in O(1) and there is no ambiguous
  // split to explore. Measured linear: 200k chars of whitespace, or of repeated `or `,
  // matches in <0.3ms. The input IS user-typed SQL (SPEC-035 editor), so this was
  // verified rather than argued.
  // eslint-disable-next-line security/detect-unsafe-regex
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
// Same as isSchemaChangingSql: star height, not backtracking. The optional group is
// anchored by `if`/`not`/`exists`, and `[a-z0-9_]*` is followed by `\s*` over a disjoint
// character class, so no input can be split two ways. Measured linear at 200k chars.
// eslint-disable-next-line security/detect-unsafe-regex
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

// ── SPEC-078: multi-statement support ─────────────────────────────────────

// Advances past a quoted region starting at `i` (buffer[i] is the opening
// quote) and returns the index just after the closing quote. Doubled quotes
// escape inside '…' strings and "…" identifiers (SQL standard); backticks
// (Hive identifiers in Athena DDL) have no escape. An unterminated quote runs
// to the end of the buffer.
function skipQuoted(buffer: string, i: number): number {
  const quote = buffer[i];
  i += 1;
  while (i < buffer.length) {
    if (buffer[i] !== quote) {
      i += 1;
      continue;
    }
    if (quote !== '`' && buffer[i + 1] === quote) {
      i += 2; // doubled-quote escape stays inside the literal
      continue;
    }
    return i + 1;
  }
  return i;
}

// Advances past a `--` line comment or `/* */` block comment starting at `i`;
// returns `i` unchanged when there is no comment there. An unterminated block
// comment runs to the end of the buffer.
function skipComment(buffer: string, i: number): number {
  if (buffer[i] === '-' && buffer[i + 1] === '-') {
    const nl = buffer.indexOf('\n', i);
    return nl === -1 ? buffer.length : nl + 1;
  }
  if (buffer[i] === '/' && buffer[i + 1] === '*') {
    const close = buffer.indexOf('*/', i + 2);
    return close === -1 ? buffer.length : close + 2;
  }
  return i;
}

// True when the segment holds anything besides whitespace and comments — a
// whitespace/comment-only segment is not a statement (FR-001).
function hasSqlContent(segment: string): boolean {
  let i = 0;
  while (i < segment.length) {
    if (/\s/.test(segment[i])) {
      i += 1;
      continue;
    }
    const afterComment = skipComment(segment, i);
    if (afterComment !== i) {
      i = afterComment;
      continue;
    }
    return true;
  }
  return false;
}

/**
 * Parses an editor buffer into its individual SQL statements (SPEC-078
 * FR-001). A semicolon terminates a statement only outside single-/double-
 * quoted strings, backtick identifiers, and line/block comments; empty
 * (whitespace/comment-only) segments are dropped. Each statement's `range`
 * is the source offsets of its trimmed text in the buffer, so a cursor or
 * selection can be mapped back to a statement (FR-006).
 */
export function splitSqlStatements(buffer: string): ParsedStatement[] {
  const statements: ParsedStatement[] = [];
  const push = (segStart: number, segEnd: number) => {
    const raw = buffer.slice(segStart, segEnd);
    if (!hasSqlContent(raw)) return;
    const leading = raw.length - raw.trimStart().length;
    const sql = raw.trim();
    statements.push({
      index: statements.length,
      sql,
      range: {start: segStart + leading, end: segStart + leading + sql.length}
    });
  };

  let segStart = 0;
  let i = 0;
  while (i < buffer.length) {
    const ch = buffer[i];
    if (ch === "'" || ch === '"' || ch === '`') {
      i = skipQuoted(buffer, i);
      continue;
    }
    const afterComment = skipComment(buffer, i);
    if (afterComment !== i) {
      i = afterComment;
      continue;
    }
    if (ch === ';') {
      push(segStart, i);
      i += 1;
      segStart = i;
      continue;
    }
    i += 1;
  }
  push(segStart, buffer.length);
  return statements;
}

/**
 * Resolves what "Run Statement" executes (SPEC-078 FR-006): a non-empty
 * selection wins (re-split per FR-001, ranges mapped back into the buffer);
 * otherwise the statement whose range contains the cursor; a cursor in the
 * whitespace between statements falls back to the nearest preceding statement
 * (or the first when the cursor precedes them all). Returns [] only when the
 * buffer holds no statements at all.
 */
export function resolveRunStatements(
  buffer: string,
  statements: ParsedStatement[],
  selection: {start: number; end: number} | null,
  cursor: number
): ParsedStatement[] {
  if (selection && selection.end > selection.start) {
    const selected = splitSqlStatements(buffer.slice(selection.start, selection.end));
    return selected.map((s) => ({
      ...s,
      range: {start: s.range.start + selection.start, end: s.range.end + selection.start}
    }));
  }
  if (statements.length <= 1) return statements.slice(0, 1);
  const containing = statements.find((s) => cursor >= s.range.start && cursor <= s.range.end);
  if (containing) return [containing];
  const preceding = [...statements].reverse().find((s) => s.range.end <= cursor);
  return [preceding ?? statements[0]];
}

/**
 * True for a statement that returns a result set worth a grid — SELECT/WITH/
 * SHOW/DESCRIBE/VALUES/EXPLAIN. DDL/DML (CREATE/INSERT/DROP/…) are false: their
 * outcome lives in history + the status bar, never a result tab (SPEC-078
 * FR-007). Leading comments/whitespace are skipped.
 */
export function isResultProducingSql(sql: string): boolean {
  return /^(select|with|show|desc|describe|values|explain)\b/i.test(stripLeadingSqlComments(sql));
}

const STATEMENT_HINT_MAX = 30;

/**
 * A short single-line hint identifying a statement in a result-tab label —
 * leading comments stripped, whitespace collapsed, truncated with an ellipsis.
 */
export function statementHint(sql: string): string {
  const collapsed = stripLeadingSqlComments(sql).replace(/\s+/g, ' ').trim();
  if (collapsed.length <= STATEMENT_HINT_MAX) return collapsed;
  return `${collapsed.slice(0, STATEMENT_HINT_MAX - 1).trimEnd()}…`;
}
