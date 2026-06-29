import type * as monaco from 'monaco-editor';
import type {GlueTableSummary} from './query.types';

// SPEC-065: schema-aware editor autocomplete. This module is intentionally
// Monaco-runtime-free at the value level (only a type-only `monaco` import) so the
// builder + provider factory are unit-testable without the editor worker.

// A framework-agnostic completion descriptor the SqlEditor maps onto Monaco's
// languages.CompletionItem (label/kind/detail/insertText).
export type SqlCompletionKind = 'table' | 'view' | 'column';

export type SqlCompletion = {
  label: string; // identifier shown + filtered on
  insertText: string; // = label (bare identifier)
  kind: SqlCompletionKind;
  detail: string; // 'table' | 'view' | `${type} · ${tableName}` for columns
};

// SPEC-048 convention: a Glue `VIRTUAL_VIEW` is a view; everything else is a table.
const VIEW_TABLE_TYPE = 'VIRTUAL_VIEW';

// Build schema completion descriptors from the active database's tables/views.
// FR-001/003/005: one item per table + view (kinded/labelled), one item per
// de-duplicated column name (with its type + table as detail). Returns [] when
// `tables` is undefined/empty; a zero-column table contributes only its own item.
export function buildSqlCompletions(tables: GlueTableSummary[] | undefined): SqlCompletion[] {
  if (!tables || tables.length === 0) return [];

  const items: SqlCompletion[] = [];
  // De-dup columns by name across tables — the same name from two tables yields a
  // single suggestion (detail reflects the first table that declared it).
  const seenColumns = new Set<string>();

  for (const table of tables) {
    const isView = table.tableType === VIEW_TABLE_TYPE;
    items.push({
      label: table.name,
      insertText: table.name,
      kind: isView ? 'view' : 'table',
      detail: isView ? 'view' : 'table'
    });
    for (const column of table.columns) {
      if (seenColumns.has(column.name)) continue;
      seenColumns.add(column.name);
      items.push({
        label: column.name,
        insertText: column.name,
        kind: 'column',
        detail: `${column.type} · ${table.name}`
      });
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

// Factory for the SQL completion provider. Reads `schemaRef.current` on every
// invocation (FR-002: latest active-database schema, never a stale closure) and
// returns schema items only — Monaco's built-in SQL keyword provider still
// contributes keywords (FR-003: we augment, not replace). Pure w.r.t. Monaco
// values (kinds come from `m`), so it is unit-testable with a fake monaco.
export function createSqlCompletionProvider(
  m: typeof monaco,
  schemaRef: {current: GlueTableSummary[] | undefined}
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
