# Spec: Autocomplete Offers the Columns of the Tables the Statement Names

**ID:** SPEC-244
**Status:** Draft
**Last Updated:** 2026-09-16
**Depends On:** SPEC-065, SPEC-077, SPEC-078

## Overview

A tester writing `SELECT * FROM denapolia.order_referring ORDER BY last_name` found the Query
editor's suggestions offering every column of every table they can reach, not the columns of the
table they were querying. The same tester asked whether suggestions could add quotes around a column
name that needs them.

This spec makes column suggestions follow the statement under the cursor. When that statement names
tables in its `FROM` and `JOIN` clauses, the editor suggests only those tables' columns. After an
alias or a table name and a dot, it suggests only that table's columns. A suggested name that SQL
would misread without quotes is inserted quoted.

### What was checked, and how

Read from the code at `73c66eef`.

- **Suggestions ignore the statement.** `buildSqlCompletions(schemas)` in
  `features/query/sqlCompletions.ts` returns every table and view as `database.table`, then every
  column of every table, de-duplicated by name across all databases, with the first declaring
  table's name as detail. `createSqlCompletionProvider` reads only the word at the cursor to set the
  replace range, and nothing reads `FROM`, `JOIN`, aliases or the rest of the buffer.
- **The schemas are already loaded.** `SqlEditor.tsx` feeds `DatabaseSchema[]` (every accessible
  database's tables, each with `columns`) into a module-level ref the provider reads on every call.
- **A statement-aware tokenizer exists.** `query.sql.ts` has `splitSqlStatements` (quote-, backtick-
  and comment-aware, with source ranges), `resolveRunStatements` (the statement at a cursor, falling
  back to the nearest preceding one), and private `skipQuoted` and `skipComment`.
- **There is no active database** (`docs/decisions/analytics.md`, Fences): every base table is
  qualified as `database.table`.
- **Names that need quoting reach the editor.** The table builder refuses new column names outside
  `[a-z0-9_]` (Fences), but a refresh skips that check to keep older tables working, a view's column
  can be any alias, and a shared space's name, which is its database name, is format-checked nowhere
  server-side (Fences). Trino requires reserved keywords to be double-quoted to be used as
  identifiers (trino.io, Reserved keywords, read 2026-09-16).

### The decisions, made while authoring

- **The statement under the cursor is the one `resolveRunStatements` would run with no selection.**
  **Run Statement** and the suggestions then agree about which statement the cursor is in, including
  when the cursor sits in the whitespace after a statement while it is being typed.
- **Every `FROM` and `JOIN` reference in that statement counts**, including those in subqueries and
  in a `WITH` clause's bodies. Scoping by subquery nesting would mean parsing SQL, while a scan of
  keywords is enough to tell `order_referring` apart from every other table the user can reach.
- **Only qualified references resolve.** `db.table` is matched against the schemas case-insensitively,
  since Athena folds unquoted names and Glue stores them lowercased. An unqualified name, or a `WITH`
  name, resolves to nothing, because with no active database there is nothing to qualify it with.
- **When no reference resolves, suggestions are today's.** A statement being typed before its `FROM`
  exists still gets every column, which is better than none.
- **Tables are still suggested alongside the scoped columns.** A user adding a `JOIN` needs them.
- **Quoting is decided per identifier part.** A part is inserted in double quotes, with inner quotes
  doubled, unless it matches `^[a-z_][a-z0-9_]*$` and is not a Trino reserved keyword. Quoting a name
  that did not need it is always valid, so the keyword list may be a superset. It is taken from Trino's
  current documentation, which may list words Athena's engine version does not reserve.
- **Inside an already-open quote, nothing is added.** When the character before the word is `"`, the
  user is quoting it themselves, so the bare name is inserted, with inner quotes doubled.

## Scope

### In Scope

- `sqlTableReferences(statement)`: the `FROM` and `JOIN` references and their aliases (FR-001).
- Finding the statement at the cursor and resolving its references against the schemas (FR-002).
- Scoped column suggestions (FR-003).
- Qualifier suggestions after `alias.` or `table.` (FR-004).
- Quoted insert text for identifiers that need it (FR-005).

### Out of Scope

- **Scoping suggestions by clause or subquery**, such as offering only aggregate-friendly columns
  after `GROUP BY`.
- **Resolving unqualified or `WITH` names**, or a subquery's output columns.
- **Keyword suggestions.** Monaco's own SQL keyword provider is unchanged.
- **Suggestions in the Data Explorer's expression box**, which is a plain input.
- **Ranking**, signature help, and hover.
- **A Help guide sentence.** The Help has no autocomplete guide today, and this spec does not add one.

---

## Functional Requirements

### FR-001: The table references a statement names

#### Description:

`query.sql.ts` exports `sqlTableReferences(statement)`, which scans the statement once, skipping
string literals and comments with the existing helpers, and returns every reference that follows
`FROM`, `JOIN` (in any join form) or a comma inside a `FROM` list. A reference is one or two
identifier parts separated by `.`, each bare (`[A-Za-z_][A-Za-z0-9_]*`) or double-quoted (with `""`
as an escaped quote). It is followed optionally by an alias, written `AS <ident>` or as a bare
identifier that is not a keyword. A keyword here is any word in `TRINO_RESERVED_KEYWORDS` (FR-005)
or in `CLAUSE_WORDS`: `LIMIT`, `OFFSET`, `FETCH`, `TABLESAMPLE`, `WINDOW`, `LATERAL`,
`MATCH_RECOGNIZE`. Those clause words are not reserved in Trino but follow a table reference. A `(` after `FROM` or `JOIN` starts a subquery, which is not a
reference, and the scan continues inside it. Keywords are matched case-insensitively, and parts keep
their spelling, unquoted.

#### Acceptance Criteria:

- [ ] `SELECT * FROM denapolia.order_referring ORDER BY last_name` returns
  `[{database: 'denapolia', table: 'order_referring', alias: null}]`.
- [ ] `select o.id from sales.orders o join "my space"."Line Items" as li on li.order_id = o.id`
  returns `orders` with alias `o` and `Line Items` in database `my space` with alias `li`.
- [ ] `SELECT * FROM a.x, b.y yy WHERE 1=1` returns both, the second with alias `yy`.
- [ ] `SELECT 'FROM fake.table' AS s -- JOIN c.d\nFROM real.t` returns only `real.t`.
- [ ] `WITH w AS (SELECT * FROM s.t) SELECT * FROM w LEFT OUTER JOIN s.u ON true` returns `s.t`,
  `{database: null, table: 'w'}` and `s.u`.
- [ ] `SELECT * FROM (SELECT * FROM s.t) sub` returns `s.t`, and nothing for `sub`.
- [ ] `SELECT * FROM s.t WHERE` returns `s.t` with alias `null`, since `WHERE` is a keyword.
- [ ] `SELECT * FROM s.t LIMIT 10` returns `s.t` with alias `null`.

### FR-002: The statement at the cursor, resolved against the schemas

#### Description:

`sqlCompletions.ts` gains `scopeAt(buffer, cursorOffset, schemas)`. It finds the statement with
`resolveRunStatements(buffer, splitSqlStatements(buffer), null, cursorOffset)`, runs
`sqlTableReferences` on it, and resolves each reference with a database part to the schema table
whose database and name match it case-insensitively. It returns the resolved tables, each with its
aliases, and nothing for references that do not resolve.

#### Acceptance Criteria:

- [ ] With schemas holding `denapolia.order_referring` (columns `last_name`, `npi`) and
  `other.claims` (`claim_id`), and the buffer `SELECT * FROM DENAPOLIA.Order_Referring ORDER BY `
  with the cursor at the end, `scopeAt` returns `order_referring` only.
- [ ] In a buffer of two statements, a cursor in the second resolves the second statement's tables,
  and a cursor in the whitespace after the first resolves the first's.
- [ ] A reference `nosuch.table` and an unqualified `orders` resolve to nothing.

### FR-003: Column suggestions follow the statement

#### Description:

`createSqlCompletionProvider` reads the model's full text and the cursor's offset on each call. When
`scopeAt` returns at least one table, and FR-004 does not apply, the suggestions are every table and
view as today, plus the columns of the resolved tables only, de-duplicated by name. Each column's
detail names every resolved table that has it. When `scopeAt` returns none, the suggestions are
exactly today's.

#### Acceptance Criteria:

- [ ] With the FR-002 schemas and buffer, the provider's column suggestions are exactly `last_name`
  and `npi`, and `claim_id` is not among them.
- [ ] The table suggestions still include `other.claims`.
- [ ] Two resolved tables that both have `id` yield one `id` suggestion whose detail names both.
- [ ] The buffer `SELECT ` with nothing else yields today's full column list, asserted against
  `buildSqlCompletions` for the same schemas.

### FR-004: After a qualifier and a dot, only that table's columns

#### Description:

When the text immediately before the word at the cursor is `<ident>.`, and `<ident>` equals,
case-insensitively, an alias of a resolved table or a resolved table's name, the suggestions are
that table's columns only: no tables and no other columns. A qualifier that matches neither falls
back to FR-003.

#### Acceptance Criteria:

- [ ] Buffer `select o. from sales.orders o join sales.items i on true`, cursor after `o.`: the
  suggestions are exactly the columns of `sales.orders`.
- [ ] Cursor after `items.` in `select items.na from sales.items`: the suggestions are exactly the
  columns of `sales.items`.
- [ ] Cursor after `x.` where `x` is no alias or table: the suggestions are FR-003's.
- [ ] Two tables aliased so that one alias equals the other's table name
  (`from s.a b join s.b c`): after `b.` the suggestions are `s.a`'s columns, since an alias wins
  over a table name.

### FR-005: A name that needs quotes is inserted quoted

#### Description:

`quoteIdentifierIfNeeded(part)` returns the part unchanged when it matches `^[a-z_][a-z0-9_]*$` and
is not in `TRINO_RESERVED_KEYWORDS`, compared case-insensitively. Otherwise it returns the part in
double quotes with inner `"` doubled. A column's `insertText` is its name through this function. A
table's `insertText` is each part through it, joined by `.`. `label` stays unquoted, so filtering and
reading are unchanged. When the character immediately before the replaced word is `"`, `insertText`
is the bare part with inner `"` doubled and no surrounding quotes. `TRINO_RESERVED_KEYWORDS` holds
the reserved keyword list published at trino.io/docs/current/language/reserved.html, with the date
it was read.

#### Acceptance Criteria:

- [ ] `last_name` inserts `last_name`. `Last Name` inserts `"Last Name"`, `order` inserts `"order"`,
  `2024_total` inserts `"2024_total"` and `a"b` inserts `"a""b"`.
- [ ] The table `my space.orders` inserts `"my space".orders`, with label `my space.orders`.
- [ ] With the text `SELECT "Las` and the cursor at the end, choosing `Last Name` inserts `Last Name`
  over `Las`, leaving a single opening quote before it.
- [ ] `TRINO_RESERVED_KEYWORDS` contains `SELECT`, `ORDER`, `GROUP` and `JSON_TABLE`, and a test
  asserts every entry is uppercase and unique.

---

## API / Interface Contract

```ts
// apps/portal/src/features/query/query.sql.ts
export type SqlTableReference = {database: string | null; table: string; alias: string | null};
export function sqlTableReferences(statement: string): SqlTableReference[];

// apps/portal/src/features/query/sqlCompletions.ts
export type ScopedTable = {database: string; table: GlueTableSummary; aliases: string[]};
export function scopeAt(buffer: string, cursorOffset: number, schemas: DatabaseSchema[] | undefined): ScopedTable[];
export function quoteIdentifierIfNeeded(part: string): string;
export const TRINO_RESERVED_KEYWORDS: ReadonlySet<string>;
```

`createSqlCompletionProvider` keeps its signature and reads `model.getValue()` and
`model.getOffsetAt(position)`.

## File & Folder Structure

```
apps/portal/src/features/query/query.sql.ts (+ queryPure.test.ts)       (FR-001)
apps/portal/src/features/query/sqlCompletions.ts                        (FR-002–FR-005)
apps/portal/src/features/query/sqlCompletions.test.ts                   (new)
apps/portal/info/component-inventory/query-feature.md
```

## Implementation Phases

### Phase 1: References and scope

- `sqlTableReferences` over the existing tokenizer helpers, and `scopeAt` (FR-001, FR-002).

### Phase 2: The provider

- Scoped columns, qualifier suggestions and quoting (FR-003–FR-005).
- The live check, run from a signed-in session after deploy: in Query, type
  `SELECT * FROM <your database>.<a table> ORDER BY ` and trigger suggestions. Only that table's
  columns are offered, alongside tables. Type `t.` after aliasing the table `t` and only its columns
  are offered. Fold it into `docs/testing/e2e.md` at completion.
