# Completed Spec — SPEC-065: Schema-Aware Editor Autocomplete (Table & Column Names)

## What was completed?

The query editor (Monaco, SPEC-035) now suggests the **active database's table, view, and column names**
alongside its built-in SQL keyword completions. Suggestions surface on as-you-type triggering and explicit
invoke (Ctrl/⌘-Space), reflect the **workspace-global active database** (SPEC-047), update when that database
changes, and degrade to keyword-only when no schema is loaded — no error, no broken popup.

- **`sqlCompletions.ts`** (NEW) — `buildSqlCompletions(tables)`: a pure, Monaco-free mapper from
  `GlueTableSummary[]` to framework-agnostic `SqlCompletion[]` descriptors. One item per **table** (kind
  `table`) and **view** (kind `view`, split on `tableType === 'VIRTUAL_VIEW'`, the SPEC-048 convention), plus
  one item per **column name de-duplicated across tables** (kind `column`, detail `` `${type} · ${tableName}` ``,
  keeping the first declaration). Returns `[]` for undefined/empty input; a zero-column table contributes only
  its own item. Same file exports **`createSqlCompletionProvider(m, schemaRef)`** — a provider factory whose
  `provideCompletionItems` reads `schemaRef.current` on every call (no stale closure), maps descriptors onto
  Monaco items (`Struct`/`Interface`/`Field` kinds from the passed `m`) with a word-replacement `range`. Kept
  runtime-free (type-only `monaco` import) so both are unit-testable without the editor worker.
- **`SqlEditor.tsx`** — gains a `completionTables?: GlueTableSummary[]` prop. A **module-level** singleton
  guards a single `registerCompletionItemProvider('sql', …)` registration (no stacking across mounts/tab
  switches), reading a module-level `schemaRef` that each render syncs from the prop (mirrors the existing
  `onRunRef` pattern). The registration is **disposed on unmount** via an effect cleanup. Keyword completions
  are untouched — Monaco's built-in SQL provider still contributes them (we augment, not replace).
- **`QueryWorkspace.tsx`** — calls `useSchema(activeDatabase || null)` (same query key as the schema rail, so
  it **shares the TanStack cache — no extra fetch**) and passes `schema?.tables` into `<SqlEditor
  completionTables=…>`.
- Tests: `sqlCompletions.test.ts` (builder cases per FR-003/005 + the provider factory's Monaco mapping and
  live-ref read with a fake monaco); `SqlEditor.test.tsx` (mocks the three monaco modules to assert
  register-exactly-once, dispose-on-unmount, and that the provider sees the latest `completionTables` through
  the shared ref).

No data-layer, Glue-service, IAM, or worker changes; no new dependencies, env vars, or `query.types.ts`
changes (reuses `GlueTableSummary`). Out-of-scope items (context-aware filtering, cross-database/`db.table`
completion, function/snippet libraries, dot-completion) were not built, per the spec.
