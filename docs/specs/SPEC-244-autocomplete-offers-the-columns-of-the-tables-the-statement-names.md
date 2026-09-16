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
- **Monaco opens suggestions only on a word.** The provider declares no `triggerCharacters`, and
  Monaco's SQL language treats `"` and whitespace as word separators, so after `t.` nothing appears
  until another letter is typed. Monaco has no SQL keyword provider: when this provider returns
  nothing, Monaco's word-based provider fills in.
- **Hive DDL quotes identifiers differently.** `lib/sql.ts` holds `sqlIdentifier` (Trino, double
  quotes) and `sqlDdlIdentifier` (Hive DDL, backticks), and the analytics Fences say the wrong one
  fails silently. SPEC-065 settled that accepting a suggestion inserts the bare identifier.
- **The completion tests live in `queryPure.test.ts`**, merged there from `sqlCompletions.test.ts`.
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
- **A `FROM` list is closed by structure, not by guessing.** It stays open at the bracket depth where
  it began until a reserved keyword other than a join word or `AS`, a clause word, or the `)` that
  closes that depth. So a comma inside a subquery's select list is not a reference separator, and a
  comma after a join's `ON` condition does not open a new reference, which is rare SQL and costs only
  a narrower suggestion list. A keyword where a table would go (`UNNEST`, `LATERAL`, `TABLE`) is not a
  reference.
- **Only qualified references resolve.** `db.table` is matched against the schemas case-insensitively,
  since Athena folds names and Glue stores them lowercased. An unqualified name, or a `WITH` name,
  resolves to nothing, because with no active database there is nothing to qualify it with.
- **When no reference resolves, suggestions are today's list.** A statement being typed before its
  `FROM` exists still gets every column, which is better than none.
- **Tables are still suggested alongside the scoped columns.** A user adding a `JOIN` needs them.
- **Typing `.` opens suggestions.** Without it, the tester's own gesture, typing an alias and a dot,
  shows nothing. A dot after a database name then suggests that database's tables and inserts the
  table name alone, which also ends today's `sales.sales.orders` result.
- **Quoting applies to Trino statements only, and supersedes SPEC-065's bare insert there.** In a
  statement whose first keyword is `SELECT`, `WITH`, `VALUES`, `INSERT` or `EXPLAIN`, or that begins
  `CREATE VIEW` or `CREATE OR REPLACE VIEW`, a part is inserted through `sqlIdentifier` unless it
  matches `^[a-z_][a-z0-9_]*$` and is not a reserved keyword. Every other statement, which includes
  the Hive DDL, gets the bare name as today, since a double-quoted name is an error there and a
  backticked one is wrong in a Trino `CREATE TABLE AS`. Quoting a name that did not need it is always
  valid in Trino, so the keyword list may be a superset. It is taken from Trino's current
  documentation, which may list words Athena's engine version does not reserve.
- **Inside an already-open quote, the user is quoting.** When the text before the cursor, scanned
  with the existing quote rules, ends inside an unclosed `"`, the replace range starts just after that
  quote, the insert is the bare name with inner quotes doubled, and no closing quote is added when one
  already follows the cursor. Only columns are offered there, since a two-part table name cannot sit
  inside one pair of quotes.
- **The keyword list and the quoter live in `lib/sql.ts`**, beside `sqlIdentifier`. `query.sql.ts`
  needs the list to recognise aliases and `sqlCompletions.ts` needs it to quote, so neither may own
  it without one importing the other in a cycle.

## Scope

### In Scope

- `sqlTableReferences(statement)`: the `FROM` and `JOIN` references and their aliases (FR-001).
- Finding the statement at the cursor and resolving its references against the schemas (FR-002).
- Scoped column suggestions (FR-003).
- Suggestions after a qualifier and a dot, and `.` as a trigger (FR-004).
- Quoted insert text in Trino statements, and completion inside an open quote (FR-005).

### Out of Scope

- **Scoping suggestions by clause or subquery**, such as offering only aggregate-friendly columns
  after `GROUP BY`.
- **Resolving unqualified or `WITH` names**, or a subquery's output columns.
- **Keyword suggestions.** This spec adds none.
- **Backtick quoting in Hive DDL.** Those statements keep the bare insert.
- **Suggestions in the Data Explorer's expression box**, which is a plain input.
- **Ranking**, signature help, and hover.
- **A Help guide sentence.** The Help has no autocomplete guide today, and this spec does not add one.

---

## Functional Requirements

### FR-001: The table references a statement names

#### Description:

`query.sql.ts` exports `sqlTableReferences(statement)`. It scans the statement once, skipping string
literals and comments with the existing helpers and tracking bracket depth. A `FROM` or a join
(`JOIN`, optionally preceded by `INNER`, `CROSS`, `NATURAL`, or `LEFT`, `RIGHT` or `FULL` with an
optional `OUTER`) expects a reference at the current depth. After a reference, a `,` at the same depth
expects another only while the `FROM` list is open. The list closes at a word in
`TRINO_RESERVED_KEYWORDS` other than a join word or `AS`, at a word in `CLAUSE_WORDS`, or at the `)`
that closes its depth.

A reference is one or two identifier parts separated by `.`, each bare (`[A-Za-z_][A-Za-z0-9_]*`) or
double-quoted (with `""` as an escaped quote), and never a word in `TRINO_RESERVED_KEYWORDS` or
`CLAUSE_WORDS`. It is followed optionally by an alias, written `AS <ident>` or as an identifier that
is not such a word. `CLAUSE_WORDS` is `LIMIT`, `OFFSET`, `FETCH`, `TABLESAMPLE`, `WINDOW`, `LATERAL`,
`MATCH_RECOGNIZE`: words Trino does not reserve that can follow a reference or stand where one would.
A `(` where a reference is expected starts a subquery, which is not a reference, and the scan
continues inside it at the next depth. Keywords are matched case-insensitively, and parts and aliases
keep their spelling, unquoted.

#### Acceptance Criteria:

- [ ] `SELECT * FROM denapolia.order_referring ORDER BY last_name` returns
  `[{database: 'denapolia', table: 'order_referring', alias: null}]`.
- [ ] `select o.id from sales.orders o join "my space"."Line Items" as li on li.order_id = o.id`
  returns `{database: 'sales', table: 'orders', alias: 'o'}` and
  `{database: 'my space', table: 'Line Items', alias: 'li'}`.
- [ ] `SELECT * FROM a.x, b.y yy WHERE 1=1` returns both, the second with alias `yy`.
- [ ] `SELECT 'FROM fake.table' AS s -- JOIN c.d\nFROM real.t` returns only `real.t`.
- [ ] `WITH w AS (SELECT * FROM s.t) SELECT * FROM w LEFT OUTER JOIN s.u ON true` returns `s.t`,
  `{database: null, table: 'w', alias: null}` and `s.u`.
- [ ] `SELECT * FROM (SELECT o.a, o.b FROM s.t o) sub` returns only `s.t` with alias `o`.
- [ ] `SELECT * FROM s.t WHERE` and `SELECT * FROM s.t LIMIT 10` each return `s.t` with alias `null`.
- [ ] `SELECT * FROM s.t CROSS JOIN UNNEST(t.arr) AS u(x)` returns only `s.t`.
- [ ] `FROM a.x JOIN b.y ON a.k = b.k, c.z` returns `a.x` and `b.y`, and not `c.z`.

### FR-002: The statement at the cursor, resolved against the schemas

#### Description:

`sqlCompletions.ts` gains `scopeAt(buffer, cursorOffset, schemas)`. It finds the statement with
`resolveRunStatements(buffer, splitSqlStatements(buffer), null, cursorOffset)`, runs
`sqlTableReferences` on it, and resolves each reference with a database part to the schema table
whose database and name match it case-insensitively. It returns the resolved tables, each with its
aliases, and nothing for references that do not resolve. A table named twice is returned once, with
every alias it was given.

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
`scopeAt` returns at least one table, and neither FR-004 nor FR-005's open-quote rule applies, the
suggestions are every table and view as today, plus the columns of the resolved tables only,
de-duplicated by name. A column's detail lists each resolved table that has it as
`<type> · <database>.<table>`, joined by `; `. When `scopeAt` returns none, the suggestions are every
table, view and column, as today, with FR-005's insert text.

#### Acceptance Criteria:

- [ ] With the FR-002 schemas and buffer, the provider's column suggestions are exactly `last_name`
  and `npi`.
- [ ] The table suggestions still include `other.claims`.
- [ ] Resolved `sales.orders (id bigint)` and `sales.items (id varchar)` yield one `id` suggestion
  whose detail is `bigint · sales.orders; varchar · sales.items`.
- [ ] The buffer `SELECT ` with nothing else yields the columns `last_name`, `npi` and `claim_id`.

### FR-004: After a qualifier and a dot

#### Description:

The provider declares `triggerCharacters: ['.']`. The qualifier is the identifier immediately before
the `.` that precedes the word at the cursor, or precedes the open quote FR-005 finds. It is compared
unquoted and case-insensitively:

- equal to an alias of a resolved table: that table's columns only;
- otherwise equal to a resolved table's name: the columns of every resolved table of that name;
- otherwise equal to a database name in the schemas: that database's tables and views, each inserted
  as its table part alone, through FR-005's quoting;
- otherwise: FR-003's suggestions.

An alias wins over a table name, and a table name over a database name.

#### Acceptance Criteria:

- [ ] Buffer `select o. from sales.orders o join sales.items i on true`, cursor after `o.`: the
  suggestions are exactly the columns of `sales.orders`.
- [ ] Cursor after `items.` in `select items.na from sales.items`: the suggestions are exactly the
  columns of `sales.items`.
- [ ] Buffer `select x. from sales.orders o`, cursor after `x.`: the suggestions are FR-003's for
  that buffer, exactly the columns of `sales.orders` plus every table.
- [ ] `from s.a b join s.b c`, cursor after `b.`: the suggestions are `s.a`'s columns.
- [ ] Buffer `select * from sales.`, cursor at the end: the suggestions are exactly `sales`'s tables
  and views, and accepting `orders` leaves `select * from sales.orders`.
- [ ] The provider's `triggerCharacters` is `['.']`.

### FR-005: Quoting in Trino statements, and completion inside an open quote

#### Description:

`lib/sql.ts` exports `TRINO_RESERVED_KEYWORDS`, the reserved keyword list published at
trino.io/docs/current/language/reserved.html with the date it was read, and
`quoteIdentifierIfNeeded(part)`, which returns the part unchanged when it matches
`^[a-z_][a-z0-9_]*$` and is not in the list, compared case-insensitively, and `sqlIdentifier(part)`
otherwise. `query.sql.ts` exports `isTrinoStatement(statement)`, true when the first keyword is
`SELECT`, `WITH`, `VALUES`, `INSERT` or `EXPLAIN`, or the statement begins `CREATE VIEW` or
`CREATE OR REPLACE VIEW`.

In a Trino statement, a column's `insertText` is `quoteIdentifierIfNeeded(name)`, and a table's is
each part through it, joined by `.`. In any other statement, `insertText` is the bare name, as
today. `label` is always unquoted, so filtering and reading are unchanged.

When the text from the statement's start to the cursor, scanned with the existing quote rules, ends
inside an unclosed `"`, only columns are suggested. The replace range starts just after that quote
and ends at the cursor, `insertText` is the bare name with inner `"` doubled, and a closing `"` is
added only when the character after the cursor is not already `"`.

#### Acceptance Criteria:

- [ ] In `SELECT ` the insert text for `last_name` is `last_name`, for `Last Name` is `"Last Name"`,
  for `order` is `"order"`, for `2024_total` is `"2024_total"` and for `a"b` is `"a""b"`.
- [ ] In `SELECT * FROM `, the table `my space.orders` inserts `"my space".orders` with label
  `my space.orders`.
- [ ] In `DROP TABLE `, the table `sales.order` inserts `sales.order`, bare.
- [ ] `SELECT "Last Na` with the cursor at the end: choosing `Last Name` leaves `SELECT "Last Name"`.
- [ ] `SELECT "Las"` with the cursor before the closing quote: choosing `Last Name` leaves
  `SELECT "Last Name"`, with one closing quote.
- [ ] Inside an open quote no table is suggested.
- [ ] `TRINO_RESERVED_KEYWORDS` contains `SELECT`, `ORDER`, `GROUP` and `JSON_TABLE`, every entry is
  uppercase, and it contains none of `CLAUSE_WORDS`.

---

## API / Interface Contract

```ts
// apps/portal/src/lib/sql.ts
export const TRINO_RESERVED_KEYWORDS: ReadonlySet<string>;
export function quoteIdentifierIfNeeded(part: string): string;

// apps/portal/src/features/query/query.sql.ts
export type SqlTableReference = {database: string | null; table: string; alias: string | null};
export const CLAUSE_WORDS: ReadonlySet<string>;
export function sqlTableReferences(statement: string): SqlTableReference[];
export function isTrinoStatement(statement: string): boolean;

// apps/portal/src/features/query/sqlCompletions.ts
export type ScopedTable = {database: string; table: GlueTableSummary; aliases: string[]};
export function scopeAt(buffer: string, cursorOffset: number, schemas: DatabaseSchema[] | undefined): ScopedTable[];
```

`createSqlCompletionProvider` keeps its signature, declares `triggerCharacters: ['.']`, and reads
`model.getValue()` and `model.getOffsetAt(position)`.

## File & Folder Structure

```
apps/portal/src/lib/sql.ts (+ its test)                                  (FR-005)
apps/portal/src/features/query/query.sql.ts                             (FR-001, FR-005)
apps/portal/src/features/query/sqlCompletions.ts                        (FR-002–FR-005)
apps/portal/src/features/query/queryPure.test.ts                        (FR-001–FR-005)
apps/portal/info/component-inventory/query-feature.md, foundations.md
```

## Implementation Phases

### Phase 1: References and scope

- `TRINO_RESERVED_KEYWORDS` in `lib/sql.ts`, `CLAUSE_WORDS`, `sqlTableReferences` over the existing
  tokenizer helpers, and `scopeAt` (FR-001, FR-002).

### Phase 2: The provider

- Scoped columns, qualifier suggestions and the trigger, quoting, and completion inside an open quote
  (FR-003–FR-005).
- The live check, run from a signed-in session after deploy: in Query, type
  `SELECT * FROM <your database>.<a table> t ORDER BY ` and trigger suggestions. Only that table's
  columns are offered, alongside tables. Type `t.`: suggestions open on the dot and offer only that
  table's columns. Type `SELECT * FROM <your database>.` and accept a table: the database is not
  repeated. Fold it into `docs/testing/e2e.md` at completion.
