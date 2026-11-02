---
type: Decision
title: "Suggestions follow the statement, and a Trino insert is quoted where the name needs it (SPEC-244)"
description: "Suggestions are scoped to the `database.table` references in the statement **Run Statement** would run, read by the tokenizer with no parser, and the whole catalog returns when none resolves; a Trino statement inserts each part through `quoteIdentifierIfNeeded`. **Autocomplete is a third identifier site and picks by STATEMENT**: `quoteIdentifierIfNeeded` quotes a suggestion's parts in a Trino statement (`SELECT`/`WITH`/`VALUES`/`INSERT`/`EXPLAIN`, `CREATE [OR REPLACE] VIEW`, and a CTAS once its `AS <query>` exists) and inserts the bare name in every other, **Iceberg's `DELETE`/`UPDATE`/`MERGE` included** — an allow-list, not a dialect test, whose misses fail LOUD, which is why a CTAS had to join it: there alone the miss was SILENT and written to a table. Its word list is **Athena's** published one, never Trino's, which omits four words Athena reserves; a superset there is safe and a subset is not."
---

A tester writing `SELECT * FROM denapolia.order_referring ORDER BY last_name` was offered every
column of every table they could reach. The provider read one thing — the word at the cursor — and
returned the whole catalog, so the more databases a user could see the less useful it got. The same
tester asked whether a name needing quotes could arrive quoted.

**The statement decides.** Suggestions are now scoped by the statement `resolveRunStatements` would
run with no selection, so **Run Statement** and the popup agree about which statement the cursor is
in, including while it is still being typed in the whitespace after the previous one.
`sqlTableReferences` reads its `FROM` and `JOIN` references with the tokenizer
`splitSqlStatements` already had; only a `database.table` reference resolves, matched
case-insensitively because Athena folds names and Glue stores them lowercased. When nothing
resolves the whole catalog comes back, which is what a statement whose `FROM` does not exist yet
deserves.

**A `FROM` list is closed by structure rather than guessed at.** It stays open at the bracket depth
where it began until a reserved word other than a join word or `AS`, a clause word, or the `)` that
closes its depth. Two consequences are load-bearing and each is held by a test whose removal was
planted and seen red: the comma re-arm is scoped to the list's own depth, so `FROM s.t AS x (a, b)`
does not read `b` as a table; and a `(` where a table would go consumes the reference slot, so a
parenthesised relation names nothing. The second is a deliberate cost — Trino's grammar does admit
`FROM (a.b)` — paid because the alternative is parsing SQL.

**Quoting picks by statement, which is the fork that fails silently.** This repo's two identifier
quoters are the trap [*Every DDL literal goes through `literal()`*](every-ddl-literal-goes-through-literal.md) names, and autocomplete is a third site for them. A Trino statement
— first keyword `SELECT`, `WITH`, `VALUES`, `INSERT` or `EXPLAIN`, or beginning `CREATE VIEW` /
`CREATE OR REPLACE VIEW` — inserts each part through `quoteIdentifierIfNeeded`, which returns the
part unchanged only when it is already lowercase, starts with a letter or underscore, holds nothing
but letters, digits and underscores, and is not reserved. Everything else keeps SPEC-065's bare
insert.

**That set is an allow-list, not a dialect test, and its complement is NOT "the Hive DDL".**
`DELETE`, `UPDATE` and `MERGE` are Trino DML on an Iceberg table and sit outside it, so a name
needing quotes arrives bare there and Athena refuses the statement. That LOUD failure is the side of
this fence to be wrong on: a double quote in Hive DDL, or a backtick in a Trino body, matches
nothing at all and says so nowhere. Widening the allow-list to those three is a straightforward
follow-up, left out of SPEC-244 rather than overlooked.

**A CTAS is INSIDE the set, and finding out why is the lesson here.** It was excluded first, on the
reasoning that `CREATE TABLE … AS SELECT` has a DDL head and a DML body so one statement needs both
quotes — and that the bare insert was the safe side because its failure would be loud. **Measuring
it falsified both halves.** The whole statement is Trino: AWS documents the body as DML, and the
head's property syntax is Trino's (`WITH (format = …, partitioned_by = ARRAY[…])`), not Hive's
`STORED AS` / `TBLPROPERTIES`. And the failure was **silent, not loud** — a column named `id total`
inserted bare parses as `id` aliased `total`, one named `2024` as the integer 2024 in every row, and
**a CTAS writes both into the new table**. Silent wrong data in a written table is worse than the
predicate-that-never-matches this fence was built around. The generalisable part: *"the failure would
be loud"* is a claim about an engine, and this one was argued rather than run. A CTAS is recognised
once its `AS <query>` has been typed — the next word after `AS` is what tells a CTAS from Hive's
`STORED AS PARQUET`, and before the body exists the statement is honestly indistinguishable from a
Hive `CREATE TABLE`.

**Read the ENGINE's keyword list, not the dialect's — this is where the first version was wrong.**
The asymmetry is what makes carrying a vendor list safe at all: quoting a name that needed no quotes
is valid, so a superset costs nothing, while a subset means a name reaches the editor bare and the
statement fails to parse. The first cut quoted from Trino's own page — 83 words, cross-checked
against that page's source in the `trinodb/trino` repository, which agreed exactly — **and it was a
subset.** Athena publishes its own `SELECT` list, and it adds `EXECUTE`, `FIRST`, `LAST` and `OF`,
so `first` and `last`, which are ordinary column names in this data, inserted bare and Athena
refused the statement; AWS's own example on that page escapes `first`. `ATHENA_RESERVED_KEYWORDS` is
the union and is what every caller consults. `TRINO_RESERVED_KEYWORDS` is kept beside it only so one
vendor page stays diffable, and a test pins both sizes and names the four, because a count alone
stays green when one word is swapped for another. Neither contains any of `CLAUSE_WORDS`, which is
what lets the two sets be consulted as one rule.

**Inside the user's own open quote, they are already quoting.** The insert becomes the bare name
with its own quotes doubled, the replace range starts just after the quote, and a closing quote is
added only when one does not already follow the cursor — which is the common case, since the SQL
language's `autoClosingPairs` inserts one the moment the user types `"`. Two traps sit here. The
existing quote scan ends at the buffer's length for **both** an unterminated quote and one closing
on the final character, so `SELECT "abc` and `SELECT "abc"` are indistinguishable by their end
offset; the scan now reports whether it found the closing quote, and without that a completion
would overwrite a finished identifier. And Monaco **discards** a suggestion whose range starts on
another line, so a quote left unclosed earlier in a multi-line statement falls through to the plain
word gesture rather than costing the user every suggestion.

**`.` is a trigger character.** Without it the tester's own gesture — an alias and a dot — showed
nothing, because Monaco treats `.` as a word separator and opens the popup only on a word. A dot
after a database name offers that database's tables inserted as the **table part alone**, which is
also what ends the `sales.sales.orders` a qualified insert produced there. The qualifier read
requires the dot: a bare word with no dot after it is a word being typed, not a qualifier, and
reading one from it would insert a bare `orders` into `select sales orders`.

**Rejected.** Scoping by clause or subquery — it needs a parser, where a keyword scan already tells
one table from every other. Resolving unqualified or `WITH` names — with no active database there is
nothing to qualify them with. Backtick quoting in Hive DDL — the bare name is correct there and a
backtick in a Trino body is not. Keyword suggestions — an empty return is not an empty popup, since
Monaco's built-in word-based provider contributes the buffer's own words. **Do not restate that last
one from `monaco.d.ts`**, which says the governing option "Defaults to true" directly above a union
with no `true` member: the comment is stale against its own type, the value the editor registers as
the default is `offWithInlineSuggestions`, and what makes it contribute here is that suppressing it
needs an inline-completions provider this app does not register. Read from the installed 0.56.0
rather than from the vendor's prose.

## History

### 2026-09-20

- **Settled:** SPEC-244.
