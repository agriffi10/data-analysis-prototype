import type * as monaco from 'monaco-editor';
import type {DatabaseSchema} from '../catalog/catalog.types';

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
 * Builds schema completion descriptors across every accessible database
 *. Tables/views are suggested **fully-qualified**
 * (`database.table`) since there is no active-database context; columns keep
 * their short form — bare name, de-duplicated across all databases, with
 * type + owning table as detail. Returns [] when there is no schema.
 */
export function buildSqlCompletions(schemas: DatabaseSchema[] | undefined): SqlCompletion[] {
  if (!schemas || schemas.length === 0) return [];

  const items: SqlCompletion[] = [];
  // De-dup columns by name across ALL tables/databases — the same name yields one
  // suggestion (detail reflects the first table that declared it).
  const seenColumns = new Set<string>();

  for (const {database, tables} of schemas) {
    for (const table of tables) {
      const isView = table.tableType === VIEW_TABLE_TYPE;
      const qualified = `${database}.${table.name}`;
      items.push({
        label: qualified,
        insertText: qualified,
        kind: isView ? 'view' : 'table',
        detail: isView ? `view · ${database}` : `table · ${database}`
      });
      for (const column of table.columns) {
        if (seenColumns.has(column.name)) continue;
        seenColumns.add(column.name);
        items.push({
          label: column.name,
          insertText: column.name,
          kind: 'column',
          detail: `${column.type} · ${qualified}`
        });
      }
    }
  }

  return items;
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
 */
export function createSqlCompletionProvider(
  m: typeof monaco,
  schemaRef: {current: DatabaseSchema[] | undefined}
): monaco.languages.CompletionItemProvider {
  return {
    provideCompletionItems(model, position) {
      // Replace the word the cursor sits in so accepting inserts the bare identifier.
      const word = model.getWordUntilPosition(position);
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn
      };
      const suggestions = buildSqlCompletions(schemaRef.current).map((c) => ({
        label: c.label,
        insertText: c.insertText,
        kind: toMonacoKind(m, c.kind),
        detail: c.detail,
        range
      }));
      return {suggestions};
    }
  };
}
