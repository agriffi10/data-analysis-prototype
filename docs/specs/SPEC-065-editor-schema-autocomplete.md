# Spec: Schema-Aware Editor Autocomplete (Table & Column Names)

**ID:** SPEC-065
**Status:** Draft
**Last Updated:** 2026-06-27
**Depends On:** SPEC-035 (Monaco `SqlEditor` + query workspace), SPEC-034 (`useSchema` + Glue services), SPEC-047 (workspace-global active database)

> **Design:** No visual design needed — this rides Monaco's native completion widget (already themed by the
> SPEC-035 `file-portal-sql` theme). The only UX surface is the suggestion popup's content and ordering.

## Overview

The query editor (Monaco, SPEC-035) provides the editor's built-in SQL **keyword** suggestions, but it knows
nothing about the user's actual schema — so it can't help complete **table** and **column** names, which is where
typos and lookups slow people down. Monaco supports registering a completion provider, and the workspace already
loads the active database's tables and columns (`useSchema`, surfaced in the schema rail). This spec wires that
schema into the editor as **type-ahead / autocomplete**: as a user types (or presses Ctrl/⌘-Space), the editor
suggests the **table and view names** and **column names** of the **currently active database**, alongside the
existing keyword completions. Suggestions update when the active database changes and degrade gracefully (keywords
only) when no schema is loaded yet.

## Scope

### In Scope

- **Schema-aware completions** — register a Monaco SQL completion provider that contributes, in addition to the
  built-in keyword suggestions: the active database's **table names**, **view names**, and **column names**.
- **Scoped to the active database** — suggestions reflect the schema of the **workspace-global active database**
  (SPEC-047); switching the active database (schema rail, SPEC-047/063) updates the suggestions. No suggestions are
  drawn from databases that aren't the active target.
- **Helpful item metadata** — column items show their data type (and originating table) as detail; table/view items
  are labelled as table vs view, so the popup is informative, not just a name list.
- **Trigger behavior** — suggestions appear via Monaco's normal as-you-type triggering and on explicit invoke
  (Ctrl/⌘-Space); accepting an item inserts the identifier at the cursor.
- **Single, non-duplicated registration** — the provider is registered exactly once for the SQL language and reads
  the **latest** active-database schema (no stacked/duplicate providers across editor mounts or tab switches), and
  is disposed when the editor tears down.
- **Graceful absence** — while the schema is loading, the database isn't provisioned yet, or there are no tables,
  the editor still works and falls back to keyword-only completions (no error, no crash).

### Out of Scope

- **Context-aware filtering** (e.g. only tables after `FROM`, only the joined tables' columns after `WHERE`, or
  `table.`→column dot-completion) — this spec offers the active database's tables/views + columns regardless of
  cursor context; smarter context parsing is a possible follow-up.
- **Cross-database / fully-qualified (`db.table`) completion** — only the active database is sourced.
- **Function / snippet libraries, signature help, hover docs, or formatting** — keywords stay Monaco's built-ins.
- Any change to the data layer, Glue services, IAM, or the self-hosted-worker setup (the completion provider runs on
  the main thread — no language-service worker, consistent with SPEC-035).
- Editing the schema-rail click-to-insert behavior (SPEC-035 FR-007) — that stays as-is and complementary.

---

## Functional Requirements

### FR-001: Register a schema-aware SQL completion provider

#### Description:

A Monaco completion provider for the `sql` language contributes table/view/column items from the active schema.

#### Acceptance Criteria:

- [ ] A completion provider is registered for the `sql` language that returns, in addition to Monaco's built-in
  keyword completions: one item per **table** and **view** name and one item per **column** name from the active
  database's loaded schema.
- [ ] The provider is registered **exactly once** — re-mounting the editor or switching query tabs does not stack
  duplicate providers (no doubled suggestions); the registration is disposed when the editor unmounts.
- [ ] Accepting a suggestion inserts the bare identifier at the cursor (the completion's `insertText` is the
  table/view/column name).

### FR-002: Scoped to the active database, updates on switch

#### Acceptance Criteria:

- [ ] The suggestions reflect the **active database's** schema (the same `useSchema(activeDatabase)` the rail uses);
  no items are sourced from non-active databases.
- [ ] When the active database changes (SPEC-047/063), subsequent completion requests reflect the new database's
  tables/views/columns (the provider reads the latest schema via a ref/store, not a stale closure).

### FR-003: Informative suggestion items

#### Acceptance Criteria:

- [ ] **Column** items use Monaco completion kind `Field`, with `detail` showing the column's data type (and its
  table name) — e.g. `string · orders`; duplicate column names across tables are de-duplicated by name in the list.
- [ ] **Table** items use kind `Struct`/`Class` and **view** items are distinguished (kind `Interface` or a `View`
  detail tag), so tables and views are visually separable in the popup.
- [ ] Built-in **keyword** suggestions are preserved (the provider augments, it does not replace, Monaco's SQL
  keyword completions).

### FR-004: Trigger behavior

#### Acceptance Criteria:

- [ ] Suggestions surface via Monaco's normal as-you-type behavior and on explicit invoke (Ctrl/⌘-Space); typing a
  prefix filters the list to matching table/view/column names.
- [ ] The completion popup does not interfere with the existing ⌘/Ctrl-Enter Run command (SPEC-035 FR-004) or the
  schema-rail click-to-insert (SPEC-035 FR-007).

### FR-005: Graceful absence of schema

#### Acceptance Criteria:

- [ ] When no schema is available (loading, database not yet provisioned, or zero tables), the editor still works
  and returns only keyword completions — no thrown error, no empty/broken popup.
- [ ] A schema with tables but a table with zero columns contributes the table name and simply no columns for it.

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover the pure builder `buildSqlCompletions(schema)`: it returns
  one item per table and view (correctly kinded/labelled) and one item per de-duplicated column name with its type
  detail; an empty/undefined schema yields no schema items; a zero-column table yields the table item only. Editor
  wiring is covered by a focused test that the provider is registered once and reads updated schema via the ref
  (mocking the Monaco languages registration), without relying on the real Monaco runtime.

---

## Data Model

```ts
// apps/portal/src/features/query/sqlCompletions.ts  (NEW — pure, Monaco-free shape)

import type {GlueTableSummary} from './query.types';

// A framework-agnostic completion descriptor the SqlEditor maps onto Monaco's
// languages.CompletionItem (label/kind/detail/insertText). Kept Monaco-free so it
// is unit-testable without the editor runtime.
export type SqlCompletionKind = 'table' | 'view' | 'column';

export type SqlCompletion = {
  label: string;       // identifier shown + filtered on
  insertText: string;  // = label (bare identifier)
  kind: SqlCompletionKind;
  detail: string;      // 'table' | 'view' | `${type} · ${tableName}` for columns
};

export function buildSqlCompletions(
  tables: GlueTableSummary[] | undefined,
): SqlCompletion[];   // [] when tables is undefined/empty
```

No new env vars, persisted state, or `query.types.ts` changes (reuses `GlueTableSummary`).

## API / Interface Contract

```ts
// SqlEditor gains a schema prop; the completion provider reads it via a ref so it
// always sees the active database's latest tables. SqlEditorHandle is unchanged.
type SqlEditorProps = {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  completionTables?: GlueTableSummary[];  // NEW: active database's tables/views (from useSchema)
};

// QueryWorkspace wiring: pass the active database's schema tables into the editor.
//   const {data: schema} = useSchema(activeDatabase || null);  // already available
//   <SqlEditor ... completionTables={schema?.tables} />
//
// Provider lifecycle (SqlEditor): register once (module-guarded), keep a mutable
// schemaRef updated from completionTables; provideCompletionItems maps
// buildSqlCompletions(schemaRef.current) -> Monaco CompletionItem[]; dispose the
// registration on unmount.
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── sqlCompletions.ts        ← NEW: buildSqlCompletions(tables) -> SqlCompletion[]
├── sqlCompletions.test.ts   ← NEW
├── SqlEditor.tsx            ← register completion provider once; read active schema via ref; new completionTables prop
├── SqlEditor.test.tsx       ← NEW (or extend): provider registered once + reads updated ref (Monaco mocked)
└── QueryWorkspace.tsx       ← pass useSchema(activeDatabase).tables into <SqlEditor completionTables=...>
```

## Implementation Phases

### Phase 1: Pure completion builder

- Add `sqlCompletions.ts` (`buildSqlCompletions`) mapping a schema's tables/views/columns to kinded, de-duplicated
  completion descriptors with type detail; full unit coverage (FR-003, FR-005, FR-006).

### Phase 2: Wire the provider into the editor

- Register a single SQL completion provider in `SqlEditor` reading a `schemaRef` updated from a new
  `completionTables` prop; map descriptors to Monaco items + keep keyword completions; dispose on unmount; pass the
  active database's schema from `QueryWorkspace` (FR-001, FR-002, FR-004).
