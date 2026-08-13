# Spec: Saved Queries in the Data Explorer

**ID:** SPEC-183
**Status:** Draft
**Last Updated:** 2026-08-13
**Depends On:** SPEC-177, SPEC-178, SPEC-181

## Overview

The `sql` arm of SPEC-178's source union finally gets a surface. A user can open a `.sql` file
from a space's `saved_queries/` folder as an exploration source — filtering, sorting and
grouping it exactly as they would a table — and can save an exploration back out as a `.sql`
file into a space of their choosing.

The asymmetry at the centre of this spec is deliberate and needs stating up front, because it is
the arc's most user-visible loss. **A saved exploration reloads as a query, not as an
exploration.** Its filters come back baked into the SQL rather than as editable chips. The
alternative — a sidecar JSON carrying the view state — is rejected: SPEC-173 settled that a
saved query is a `.sql` **file** in an ordinary folder, and a sidecar would reintroduce exactly
the JSON store that spec deleted, plus a second artifact to keep in sync with a file users can
freely rename, edit or delete from the file browser.

## Scope

### In Scope

- Loading a `.sql` file as a `{kind: 'sql'}` exploration source.
- Saving an exploration's **rendered** SQL as a `.sql` file, into a chosen space.
- The two refusals a wrapped subquery requires: multi-statement files, and statements that are
  not `SELECT` or `WITH … SELECT`.
- The load surface — a space selector and the paged list, over SPEC-177's shared store.
- Registry rows for both space selectors under `sharedWorkspaces`, and for the load and save
  surfaces under `dataExplorer`.

### Out of Scope

- **Any new store, format, sidecar or metadata.** Nothing is written but a `.sql` file.
- **Migrating or rewriting existing saved queries.** A file written by the Query workspace opens
  here and vice versa; neither is converted.
- **Reconstructing an exploration's view state from SQL.** Explicitly rejected — it needs a SQL
  parser and would be wrong in ways a user could not see.
- **Editing the loaded SQL.** The Data Explorer has no SQL editor; a file that needs editing
  belongs in the Query workspace, which is one click away.
- **`SavedQueriesPanel`** — the Query workspace's own rail panel, untouched.
- Changing any SPEC-173/174/175 rule.

---

## Functional Requirements

### FR-001: Loading a `.sql` file as a source

#### Description:

A load surface lists a space's saved queries and opens the chosen one as a `sql` source in a new
exploration tab.

#### Acceptance Criteria:

- [ ] The list is SPEC-174's: paged over filtered `.sql` rows, in S3's own order, with the
      keep-fetching fill and its error stop.
- [ ] Opening a file creates a tab whose source is `{kind: 'sql', body, label}`, where `label`
      is the file's name without its extension.
- [ ] The first execution runs the wrapped SQL and the grid adopts the columns the execution
      reports (SPEC-180 FR-006).
- [ ] Filters, ordering and grouping then apply over the wrapped source exactly as over a table
      — asserted by rendering the same query description against both source arms.
- [ ] A file that cannot be read leaves the tab unopened and shows the mapped message; it does
      not open an empty exploration.
- [ ] The space selector offers My files plus active shared spaces, and with `sharedWorkspaces`
      off offers My files alone, filtered at the **view** (SPEC-174's deviation, repeated here
      deliberately) — under its own registry row.

### FR-002: The two refusals

#### Description:

The `sql` arm wraps the file's body in a subquery. Two shapes cannot be wrapped, and both are
refused by the app with its own wording rather than being sent to Athena to fail.

#### Acceptance Criteria:

- [ ] A file whose body yields more than one statement through `splitSqlStatements` is refused,
      and the message says the Data Explorer opens a single statement.
- [ ] A body whose first keyword is neither `SELECT` nor `WITH` is refused. `WITH … SELECT` is
      **allowed** — a CTE is an ordinary way to write a query, and excluding it would refuse
      files the Query workspace happily runs.
- [ ] The keyword check ignores leading comments and whitespace.
- [ ] A trailing semicolon is stripped rather than refused, since `splitSqlStatements` already
      normalises it.
- [ ] Refusals render through `lib/errorMessages.ts` (SPEC-106); no Athena text is involved,
      because no query was sent.
- [ ] A refused file leaves no tab open and no execution issued.

### FR-003: Saving an exploration

#### Description:

Saving writes the exploration's **rendered** SQL — filters, expression, ordering and grouping
included — through SPEC-177's generalized save flow.

Rendered rather than source, because what the user is looking at is what the file should
reproduce. Saving the bare source would produce a file that reopens as something the user did
not save.

#### Acceptance Criteria:

- [ ] The saved body is the string `renderExplorationSql` produced for the **currently displayed**
      execution — read from the same place the execution used, never re-derived.
- [ ] The save dialog is SPEC-177's, asking for a name and a destination space.
- [ ] Every SPEC-175 rule holds: every save prompts; an unchanged re-save is confirmed once;
      `isLinkedSavedQuery` is the single predicate behind the dialog's promise and the host's
      `overwrite`; choosing another space is a copy; a write failure keeps the dialog open with
      the mapped message inline.
- [ ] `savedQueryName` still lowercases a typed extension while the stem stays case-sensitive
      (SPEC-175's correction) — asserted here too, because this is a second caller.
- [ ] The destination selector is a second instance of the `sharedWorkspaces` choice and gets
      **its own registry row**, as SPEC-175 found it needed one — this one offers a colleague's
      space as a write target.
- [ ] Saving issues no Athena execution.

### FR-004: A saved exploration reloads as a query

#### Description:

The accepted loss, asserted rather than left to be discovered.

#### Acceptance Criteria:

- [ ] Saving an exploration with filters and a sort, then loading that file, produces a `sql`
      source whose body contains those clauses and whose query description is **empty**.
- [ ] The load surface says the file opens as a query, so the absence of chips is expected
      rather than a bug.
- [ ] No sidecar, manifest or metadata object is written — asserted by counting `PutObject`
      calls on a save: exactly one.
- [ ] The delivery doc records the rejected sidecar alternative and why.

### FR-005: The two features' files are interchangeable

#### Description:

There is one store, so a file saved in either surface opens in the other.

#### Acceptance Criteria:

- [ ] A file saved from the Query workspace appears in the Data Explorer's load list and opens.
- [ ] A file saved from the Data Explorer appears in the Query workspace's saved-queries panel
      and opens into an editor tab.
- [ ] Neither surface writes anything the other cannot read.
- [ ] The Data Explorer's load list applies the same top-level `.sql` filter with
      `Delimiter: '/'` — it does not list subfolders' files (SPEC-173).

---

## Data Model

No new persisted types. The source arm from SPEC-178, now reachable:

```ts
export type ExplorationSource =
  | {kind: 'table'; spaceId: string; database: string; table: string}
  | {kind: 'sql'; body: string; label: string};
```

The refusal codes:

```ts
export type SqlSourceRefusal = 'multipleStatements' | 'notASelect';
```

---

## API / Interface Contract

```ts
/**
 * Validates a saved file's body as an exploration source.
 * Returns the normalized single statement, or the reason it cannot be one.
 */
export function toSqlSource(
  body: string,
  label: string
): {ok: true; source: ExplorationSource} | {ok: false; reason: SqlSourceRefusal};
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── LoadQueryDialog.tsx
├── SaveExplorationDialog.tsx      # thin host over SPEC-177's SaveQueryDialog
├── toSqlSource.ts
├── toSqlSource.test.ts
└── savedQueriesInExplorer.test.tsx
```

---

## Implementation Phases

### Phase 1: The source validator

- `toSqlSource` with both refusals, the comment-tolerant keyword check and the `WITH` allowance.

### Phase 2: Loading

- The load dialog over SPEC-177's pager and space selector, with the view-level
  `sharedWorkspaces` filter and its registry row.
- Opening a `sql`-source tab and running its first execution.

### Phase 3: Saving

- The rendered-SQL save through SPEC-177's generalized flow, with the destination selector's own
  registry row.
- The single-`PutObject` assertion and the reload-as-a-query test.

### Phase 4: Interchange

- The both-directions tests between the two features' surfaces.
