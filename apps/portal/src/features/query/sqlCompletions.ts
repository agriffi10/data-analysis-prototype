import type * as monaco from 'monaco-editor';
import {quoteIdentifierIfNeeded} from '../../lib/sql';
import type {DatabaseSchema, GlueTableSummary} from '../catalog/catalog.types';
import {
  isTrinoStatement,
  openQuoteStart,
  resolveRunStatements,
  splitSqlStatements,
  sqlQualifierBefore,
  sqlTableReferences
} from './query.sql';
import type {ParsedStatement} from './query.types';

// Schema-aware editor autocomplete. Intentionally Monaco-runtime-free at the
// value level (only a type-only `monaco` import) so the builder + provider
// factory are unit-testable without the editor worker.

export type SqlCompletionKind = 'table' | 'view' | 'column';

/** Framework-agnostic completion descriptor the SqlEditor maps onto Monaco's CompletionItem. */
export type SqlCompletion = {
  /** Identifier shown + filtered on. */
  label: string;
  /** Equals label (bare identifier). */
  insertText: string;
  kind: SqlCompletionKind;
  /** 'table' | 'view' | `${type} · ${tableName}` for columns. */
  detail: string;
};

// A Glue `VIRTUAL_VIEW` is a view; everything else is a table.
const VIEW_TABLE_TYPE = 'VIRTUAL_VIEW';

/**
 * Builds schema completion descriptors across every accessible database.
 * Tables/views are suggested **fully-qualified**
 * (`database.table`) since there is no active-database context; columns keep
 * their short form — bare name, de-duplicated across all databases, with
 * type + owning table as detail. Returns [] when there is no schema.
 */
export function buildSqlCompletions(schemas: DatabaseSchema[] | undefined): SqlCompletion[] {
  return schemaSources(schemas).map((source) => toCompletion(source, false, null));
}

// A descriptor before its insert text is decided, carrying the identifier PARTS the insert is built
// from — one for a column, two for a fully-qualified table. The parts are what the Trino quoter
// needs: joining first and splitting later would mangle a name that itself holds a dot.
type CompletionSource = {label: string; parts: string[]; kind: SqlCompletionKind; detail: string};

// Every accessible database's tables/views fully qualified, and every column once, de-duped by name
// across all databases with the first declaring table as detail.
function schemaSources(schemas: DatabaseSchema[] | undefined): CompletionSource[] {
  if (!schemas || schemas.length === 0) return [];

  const sources: CompletionSource[] = [];
  const seenColumns = new Set<string>();

  for (const {database, tables} of schemas) {
    for (const table of tables) {
      const isView = table.tableType === VIEW_TABLE_TYPE;
      sources.push({
        label: `${database}.${table.name}`,
        parts: [database, table.name],
        kind: isView ? 'view' : 'table',
        detail: isView ? `view · ${database}` : `table · ${database}`
      });
      for (const column of table.columns) {
        if (seenColumns.has(column.name)) continue;
        seenColumns.add(column.name);
        sources.push({
          label: column.name,
          parts: [column.name],
          kind: 'column',
          detail: `${column.type} · ${database}.${table.name}`
        });
      }
    }
  }

  return sources;
}

/** One table a statement names, resolved against the schemas, with every alias it was given. */
export type ScopedTable = {database: string; table: GlueTableSummary; aliases: string[]};

// The statement "Run Statement" would run with no selection: the one the cursor sits in, or the
// nearest preceding one when it sits in the whitespace after a statement being typed. Suggestions
// and the run button then agree about which statement the cursor is in.
function statementAt(buffer: string, cursorOffset: number): ParsedStatement | null {
  const statements = splitSqlStatements(buffer);
  if (statements.length === 0) return null;
  return resolveRunStatements(buffer, statements, null, cursorOffset)[0] ?? null;
}

function resolveScope(statement: ParsedStatement | null, schemas: DatabaseSchema[] | undefined): ScopedTable[] {
  if (!statement || !schemas || schemas.length === 0) return [];

  const scoped: ScopedTable[] = [];
  const byTable = new Map<string, ScopedTable>();

  for (const reference of sqlTableReferences(statement.sql)) {
    const referenced = reference.database;
    if (referenced === null) continue;
    const schema = schemas.find((s) => s.database.toLowerCase() === referenced.toLowerCase());
    const table = schema?.tables.find((t) => t.name.toLowerCase() === reference.table.toLowerCase());
    if (!schema || !table) continue;

    const key = JSON.stringify([schema.database.toLowerCase(), table.name.toLowerCase()]);
    let entry = byTable.get(key);
    if (!entry) {
      entry = {database: schema.database, table, aliases: []};
      byTable.set(key, entry);
      scoped.push(entry);
    }
    if (reference.alias !== null && !entry.aliases.includes(reference.alias)) entry.aliases.push(reference.alias);
  }

  return scoped;
}

/**
 * The tables the statement at the cursor names, resolved against the loaded schemas.
 *
 * Only a `database.table` reference resolves: matched case-insensitively, since Athena folds names
 * and Glue stores them lowercased. An unqualified name — a CTE, or a table written without its
 * database — resolves to nothing, because the workspace has no active database to qualify it with.
 * An empty result is the signal to suggest everything, which is what a statement whose `FROM` has
 * not been typed yet deserves.
 *
 * @param buffer - The whole editor buffer.
 * @param cursorOffset - The cursor as a buffer offset.
 * @param schemas - Every accessible database's schema, or undefined while none is loaded.
 * @returns One entry per distinct resolved table, in the order the statement names them.
 */
export function scopeAt(buffer: string, cursorOffset: number, schemas: DatabaseSchema[] | undefined): ScopedTable[] {
  return resolveScope(statementAt(buffer, cursorOffset), schemas);
}

// Every resolved table's columns, de-duped by name; a name several of them declare lists one detail
// per table, so the popup says which of the statement's tables it came from.
function scopedColumnSources(tables: ScopedTable[]): CompletionSource[] {
  const details = new Map<string, string[]>();
  const order: string[] = [];

  for (const {database, table} of tables) {
    for (const column of table.columns) {
      const detail = `${column.type} · ${database}.${table.name}`;
      const seen = details.get(column.name);
      if (seen) {
        seen.push(detail);
        continue;
      }
      details.set(column.name, [detail]);
      order.push(column.name);
    }
  }

  return order.map((name) => ({
    label: name,
    parts: [name],
    kind: 'column' as const,
    detail: (details.get(name) ?? []).join('; ')
  }));
}

// One database's tables and views, inserted as the table part ALONE — the user has already typed
// `database.`, and repeating it is what produced `sales.sales.orders`.
function databaseTableSources({database, tables}: DatabaseSchema): CompletionSource[] {
  return tables.map((table) => {
    const isView = table.tableType === VIEW_TABLE_TYPE;
    return {
      label: table.name,
      parts: [table.name],
      kind: isView ? ('view' as const) : ('table' as const),
      detail: isView ? `view · ${database}` : `table · ${database}`
    };
  });
}

// What to offer, in precedence order: an alias beats a table name, a table name beats a database
// name, and an unrecognised qualifier falls through to the statement's own scope.
function sourcesFor(
  qualifier: string | null,
  scoped: ScopedTable[],
  schemas: DatabaseSchema[] | undefined
): CompletionSource[] {
  if (qualifier !== null) {
    const wanted = qualifier.toLowerCase();
    const byAlias = scoped.filter((s) => s.aliases.some((alias) => alias.toLowerCase() === wanted));
    if (byAlias.length > 0) return scopedColumnSources(byAlias);
    const byName = scoped.filter((s) => s.table.name.toLowerCase() === wanted);
    if (byName.length > 0) return scopedColumnSources(byName);
    const schema = schemas?.find((s) => s.database.toLowerCase() === wanted);
    if (schema) return databaseTableSources(schema);
  }
  if (scoped.length > 0) {
    // Tables stay in the list alongside the scoped columns — a user adding a JOIN needs them.
    return [...schemaSources(schemas).filter((s) => s.kind !== 'column'), ...scopedColumnSources(scoped)];
  }
  return schemaSources(schemas);
}

// The label is always the bare identifier, so filtering and reading never see a quote. The insert
// text is the dialect's business: each part through the Trino quoter in a Trino statement, the bare
// name in the Hive DDL, and — when `closeQuote` is not null, meaning the cursor is inside the user's
// own open quote — the bare name with its quotes doubled, closed only if they have not closed it.
function toCompletion(source: CompletionSource, trino: boolean, closeQuote: boolean | null): SqlCompletion {
  const joined = source.parts.join('.');
  let insertText = joined;
  if (closeQuote !== null) insertText = `${joined.replace(/"/g, '""')}${closeQuote ? '"' : ''}`;
  else if (trino) insertText = source.parts.map(quoteIdentifierIfNeeded).join('.');
  return {label: source.label, insertText, kind: source.kind, detail: source.detail};
}

// Map our framework-agnostic kind onto Monaco's CompletionItemKind: tables as
// Struct, views as Interface (so they read as distinct in the popup), columns as
// Field. The Monaco enum is sourced from the passed `m` so this stays runtime-free.
function toMonacoKind(m: typeof monaco, kind: SqlCompletionKind): monaco.languages.CompletionItemKind {
  switch (kind) {
    case 'table':
      return m.languages.CompletionItemKind.Struct;
    case 'view':
      return m.languages.CompletionItemKind.Interface;
    case 'column':
      return m.languages.CompletionItemKind.Field;
  }
}

/**
 * Factory for the SQL completion provider. Reads `schemaRef.current` on every
 * invocation (latest schemas across all accessible databases, never a stale
 * closure) and returns schema items only — Monaco's built-in SQL keyword
 * provider still contributes keywords (augment, not replace). Pure w.r.t.
 * Monaco values (kinds come from `m`), so it is unit-testable with a fake monaco.
 *
 * Every call re-reads the buffer and the cursor, because the suggestions follow the statement the
 * cursor is in: the columns of the tables that statement names, the columns of one of them after an
 * alias and a dot, or that database's tables after a database name and a dot. `.` is a trigger
 * character, without which the alias gesture shows nothing until another letter is typed.
 */
export function createSqlCompletionProvider(
  m: typeof monaco,
  schemaRef: {current: DatabaseSchema[] | undefined}
): monaco.languages.CompletionItemProvider {
  return {
    triggerCharacters: ['.'],
    provideCompletionItems(model, position) {
      const schemas = schemaRef.current;
      const buffer = model.getValue();
      const cursorOffset = model.getOffsetAt(position);
      const word = model.getWordUntilPosition(position).word;

      const statement = statementAt(buffer, cursorOffset);
      // `splitSqlStatements` trims, so the cursor routinely sits past a statement's end — in the
      // space after `ORDER BY `, which is exactly where suggestions are asked for.
      const base = statement ? statement.range.start : 0;
      const typed = base <= cursorOffset ? buffer.slice(base, cursorOffset) : '';

      const quoteStart = openQuoteStart(typed);
      // Monaco discards a suggestion whose range starts on another line, so a quote left unclosed
      // earlier in a multi-line statement falls through to the plain word gesture rather than
      // costing the user every suggestion.
      const quoting = quoteStart !== null && !typed.slice(quoteStart).includes('\n');
      const replaceStart = quoting ? base + (quoteStart as number) : cursorOffset - word.length;
      // The qualifier sits before the token being replaced, which is the open quote itself when the
      // user is already quoting.
      const qualifier = sqlQualifierBefore(typed, (quoting ? replaceStart - 1 : replaceStart) - base);

      let sources = sourcesFor(qualifier, resolveScope(statement, schemas), schemas);
      // A two-part table name cannot sit inside one pair of quotes, so only columns go there.
      if (quoting) sources = sources.filter((source) => source.kind === 'column');

      const trino = statement ? isTrinoStatement(statement.sql) : false;
      const closeQuote = quoting ? buffer[cursorOffset] !== '"' : null;
      const start = model.getPositionAt(replaceStart);
      const range = {
        startLineNumber: start.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: start.column,
        endColumn: position.column
      };

      const suggestions = sources.map((source) => {
        const completion = toCompletion(source, trino, closeQuote);
        return {
          label: completion.label,
          insertText: completion.insertText,
          kind: toMonacoKind(m, completion.kind),
          detail: completion.detail,
          range
        };
      });
      return {suggestions};
    }
  };
}
