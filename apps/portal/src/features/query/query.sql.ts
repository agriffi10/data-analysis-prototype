// SQL-statement classification + splitting helpers for the query workspace.

import {TRINO_RESERVED_KEYWORDS} from '../../lib/sql';
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
  // matches in <0.3ms. The input IS user-typed SQL, so this was
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
 * fully-qualified `database.object` — there's no active database to
 * assume. Returns null when the statement isn't schema-changing or its target
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
 * Derives the target database for a "Create view" from the view body itself:
 * the single database of the fully-qualified base tables the
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

// ── Multi-statement support ──────────────────────────────────────────────

// Scans the quoted region starting at `i` (buffer[i] is the opening quote) and reports the index
// just after it, plus whether a closing quote was actually found. Doubled quotes escape inside '…'
// strings and "…" identifiers (SQL standard); backticks (Hive identifiers in Athena DDL) have no
// escape. An unterminated quote runs to the end of the buffer — and `end` alone cannot tell the two
// apart, since a quote closing on the buffer's last character also ends at `buffer.length`, which is
// why `terminated` is reported separately.
function scanQuoted(buffer: string, i: number): {end: number; terminated: boolean} {
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
    return {end: i + 1, terminated: true};
  }
  return {end: i, terminated: false};
}

// Advances past a quoted region starting at `i` and returns the index just after it, closed or not.
function skipQuoted(buffer: string, i: number): number {
  return scanQuoted(buffer, i).end;
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
// whitespace/comment-only segment is not a statement.
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
 * Parses an editor buffer into its individual SQL statements.
 * A semicolon terminates a statement only outside single-/double-
 * quoted strings, backtick identifiers, and line/block comments; empty
 * (whitespace/comment-only) segments are dropped. Each statement's `range`
 * is the source offsets of its trimmed text in the buffer, so a cursor or
 * selection can be mapped back to a statement.
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
 * Resolves what "Run Statement" executes: a non-empty
 * selection wins (re-split, ranges mapped back into the buffer);
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
 * outcome lives in history + the status bar, never a result tab.
 * Leading comments/whitespace are skipped.
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

// ── Statement-aware completion support ──────────────────────────────────

/** One `FROM`/`JOIN` reference: `database` is null for an unqualified name, which resolves to nothing. */
export type SqlTableReference = {database: string | null; table: string; alias: string | null};

/**
 * Words Trino does NOT reserve that can follow a table reference or stand where one would.
 *
 * The second half of the "what ends a `FROM` list" rule, beside `TRINO_RESERVED_KEYWORDS`: a
 * reserved word cannot be an alias because it is a keyword, and these cannot be one because the
 * grammar gives them their own meaning in that position. The two sets are disjoint by construction —
 * every word here was checked against the reserved list.
 */
export const CLAUSE_WORDS: ReadonlySet<string> = new Set([
  'LIMIT',
  'OFFSET',
  'FETCH',
  'TABLESAMPLE',
  'WINDOW',
  'LATERAL',
  'MATCH_RECOGNIZE'
]);

// The words that may precede JOIN in a join clause. They must not close an open FROM list, which is
// the only reason the set exists — `JOIN` itself is what arms the next reference.
const JOIN_WORDS: ReadonlySet<string> = new Set([
  'JOIN',
  'INNER',
  'CROSS',
  'NATURAL',
  'LEFT',
  'RIGHT',
  'FULL',
  'OUTER'
]);

// Statements Athena runs through Trino, by their first keyword. CREATE VIEW is Trino too and is
// recognised separately; everything absent here — the Hive DDL — is not.
const TRINO_LEADING_KEYWORDS: ReadonlySet<string> = new Set(['SELECT', 'WITH', 'VALUES', 'INSERT', 'EXPLAIN']);

type SqlToken = {
  /** `quoted` is a `"…"` identifier with its escapes resolved; `other` is a string literal or a backtick name. */
  kind: 'word' | 'quoted' | 'punct' | 'other';
  text: string;
  end: number;
};

// Reads the next token at or after `from`, skipping whitespace and comments; null at the end.
function nextSqlToken(buffer: string, from: number): SqlToken | null {
  let i = from;
  while (i < buffer.length) {
    if (/\s/.test(buffer[i])) {
      i += 1;
      continue;
    }
    const afterComment = skipComment(buffer, i);
    if (afterComment === i) break;
    i = afterComment;
  }
  if (i >= buffer.length) return null;
  const ch = buffer[i];
  if (ch === '"') {
    const {end, terminated} = scanQuoted(buffer, i);
    const inner = buffer.slice(i + 1, terminated ? end - 1 : end);
    return {kind: 'quoted', text: inner.replace(/""/g, '"'), end};
  }
  if (ch === "'" || ch === '`') {
    const {end} = scanQuoted(buffer, i);
    return {kind: 'other', text: buffer.slice(i, end), end};
  }
  if (/[A-Za-z_]/.test(ch)) {
    let j = i + 1;
    while (j < buffer.length && /[A-Za-z0-9_]/.test(buffer[j])) j += 1;
    return {kind: 'word', text: buffer.slice(i, j), end: j};
  }
  return {kind: 'punct', text: ch, end: i + 1};
}

// One identifier part of a table reference, or an alias: a bare word that is neither reserved nor a
// clause word, or a `"…"` name, which may be either. Null for anything else, which is what stops
// `FROM` + UNNEST, LATERAL or a keyword being read as a table.
function referencePart(token: SqlToken): string | null {
  if (token.kind === 'quoted') return token.text;
  if (token.kind !== 'word') return null;
  const upper = token.text.toUpperCase();
  if (TRINO_RESERVED_KEYWORDS.has(upper) || CLAUSE_WORDS.has(upper)) return null;
  return token.text;
}

// Reads one reference — one or two parts, then an optional `AS alias` or bare alias — starting at
// the already-read `first` token. Null when `first` is not a reference at all, which closes the list.
function readReference(statement: string, first: SqlToken): {reference: SqlTableReference; end: number} | null {
  const firstPart = referencePart(first);
  if (firstPart === null) return null;

  let database: string | null = null;
  let table = firstPart;
  let end = first.end;
  const dot = nextSqlToken(statement, end);
  if (dot && dot.kind === 'punct' && dot.text === '.') {
    const second = nextSqlToken(statement, dot.end);
    const secondPart = second ? referencePart(second) : null;
    if (second === null || secondPart === null) return null;
    database = firstPart;
    table = secondPart;
    end = second.end;
  }

  const after = nextSqlToken(statement, end);
  if (after?.kind === 'word' && after.text.toUpperCase() === 'AS') {
    const aliasToken = nextSqlToken(statement, after.end);
    const alias = aliasToken ? referencePart(aliasToken) : null;
    if (aliasToken && alias !== null) return {reference: {database, table, alias}, end: aliasToken.end};
    return {reference: {database, table, alias: null}, end: after.end};
  }
  const alias = after ? referencePart(after) : null;
  if (after && alias !== null) return {reference: {database, table, alias}, end: after.end};
  return {reference: {database, table, alias: null}, end};
}

/**
 * The tables a single statement names in its `FROM` and `JOIN` clauses, with their aliases.
 *
 * Every reference counts, including those in subqueries and in a `WITH` clause's bodies: scoping by
 * nesting would mean parsing SQL, and a scan of keywords is already enough to tell one table apart
 * from every other the user can reach. An unqualified name — a CTE, or a name written without its
 * database — comes back with a null `database` and resolves to nothing, since the workspace has no
 * active database to qualify it with.
 *
 * A `FROM` list stays open at the bracket depth where it began and closes at the first reserved word
 * that is not a join word or `AS`, at a clause word, or at the `)` that closes its depth. So a comma
 * inside a subquery's select list does not separate references, and a comma after a join's `ON`
 * condition does not open one — rare SQL whose cost is a narrower suggestion list, never a wrong one.
 *
 * @param statement - One SQL statement, as `splitSqlStatements` returns it.
 * @returns The references in source order; a table named twice appears twice.
 */
export function sqlTableReferences(statement: string): SqlTableReference[] {
  const references: SqlTableReference[] = [];
  let depth = 0;
  // The open FROM/JOIN list: the bracket depth it began at, and whether the next token is read as a
  // reference. Null when no list is open, which is when identifiers are ignored.
  let list: {depth: number; expecting: boolean} | null = null;
  let i = 0;

  for (;;) {
    const token = nextSqlToken(statement, i);
    if (!token) break;
    i = token.end;
    const upper = token.kind === 'word' ? token.text.toUpperCase() : '';

    if (token.kind === 'punct' && token.text === '(') {
      // A subquery where a reference was expected fills the slot without being one.
      if (list) list.expecting = false;
      depth += 1;
      continue;
    }
    if (token.kind === 'punct' && token.text === ')') {
      depth -= 1;
      if (list && depth < list.depth) list = null;
      continue;
    }
    if (upper === 'FROM' || upper === 'JOIN') {
      list = {depth, expecting: true};
      continue;
    }
    if (!list) continue;

    if (list.expecting) {
      const read = readReference(statement, token);
      if (!read) {
        list = null;
        continue;
      }
      references.push(read.reference);
      list.expecting = false;
      i = read.end;
      continue;
    }
    if (token.kind === 'punct' && token.text === ',' && depth === list.depth) {
      list.expecting = true;
      continue;
    }
    if (
      token.kind === 'word' &&
      upper !== 'AS' &&
      !JOIN_WORDS.has(upper) &&
      (TRINO_RESERVED_KEYWORDS.has(upper) || CLAUSE_WORDS.has(upper))
    ) {
      list = null;
    }
  }

  return references;
}

/**
 * True when Athena runs this statement through Trino rather than Hive.
 *
 * Decides which identifier quote a name may carry: a Trino statement takes double quotes, and
 * everything else — the Hive DDL — takes the bare name, because a double-quoted name is an error
 * there and a backticked one is wrong in a Trino `CREATE TABLE AS`. `CREATE TABLE` is deliberately
 * outside the set, which is the safe side of that fence.
 *
 * @param statement - One SQL statement; leading comments and whitespace are skipped.
 * @returns True for SELECT/WITH/VALUES/INSERT/EXPLAIN and for CREATE [OR REPLACE] VIEW.
 */
export function isTrinoStatement(statement: string): boolean {
  const first = nextSqlToken(statement, 0);
  if (first?.kind !== 'word') return false;
  const upper = first.text.toUpperCase();
  if (TRINO_LEADING_KEYWORDS.has(upper)) return true;
  if (upper !== 'CREATE') return false;

  let next = nextSqlToken(statement, first.end);
  if (next?.kind === 'word' && next.text.toUpperCase() === 'OR') {
    const replace = nextSqlToken(statement, next.end);
    if (replace?.kind !== 'word' || replace.text.toUpperCase() !== 'REPLACE') return false;
    next = nextSqlToken(statement, replace.end);
  }
  return next?.kind === 'word' && next.text.toUpperCase() === 'VIEW';
}

/**
 * The offset just after an unclosed `"` the text ends inside, or null when it ends outside one.
 *
 * The "is the user already quoting?" test, scanned with the same quote and comment rules as
 * `splitSqlStatements` so the two agree about what a quote is. A `'…'` string or a backtick name
 * left open returns null: the cursor is inside a literal, not inside an identifier.
 *
 * @param text - The statement's text from its start up to the cursor.
 * @returns The offset of the first character inside the open quote, or null.
 */
export function openQuoteStart(text: string): number | null {
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "'" || ch === '"' || ch === '`') {
      const {end, terminated} = scanQuoted(text, i);
      if (!terminated) return ch === '"' ? i + 1 : null;
      i = end;
      continue;
    }
    const afterComment = skipComment(text, i);
    if (afterComment !== i) {
      i = afterComment;
      continue;
    }
    i += 1;
  }
  return null;
}

/**
 * The identifier written immediately before the `.` at `end`, unquoted, or null.
 *
 * The "what did the user qualify this with?" read the completion provider needs, expressed once here
 * because the tokenizer that knows what an identifier is lives here. A string literal or a backtick
 * name before the dot is not a qualifier and returns null, as does a dot with nothing before it.
 *
 * @param text - The statement's text from its start; offsets are relative to it.
 * @param end - The offset of the token the qualifier would precede, so `text[end - 1]` is the dot.
 * @returns The identifier, with any `"` quoting resolved, or null when there is no qualifier there.
 */
export function sqlQualifierBefore(text: string, end: number): string | null {
  if (end <= 0 || text[end - 1] !== '.') return null;
  const dot = end - 1;
  let qualifier: string | null = null;
  let i = 0;
  for (;;) {
    const token = nextSqlToken(text, i);
    if (!token || token.end > dot) break;
    if (token.end === dot) qualifier = token.kind === 'word' || token.kind === 'quoted' ? token.text : null;
    i = token.end;
  }
  return qualifier;
}
