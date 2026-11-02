---
type: Decision
title: "A statement handed to the Data Explorer runs again, and a result it cannot name is not explorable (SPEC-242)"
description: "*Explore in Data Explorer* re-runs the statement as a billed `sql` source and evicts only that body's cached executions; only `SELECT`, `WITH` and `VALUES` are explorable, and a result with an unnamed or duplicate column is refused whole."
---

*Explore in Data Explorer* opens a Query result's statement as a `sql` source — the first surface to
reach that arm. The hand-off's mechanism, router state read once per history entry, is a browser
decision and lives in [`docs/decisions/browser/`](../browser/sibling-features-hand-off-through-router-state-read-once-per-history.md);
what is recorded here is what the Explorer does with the statement.

**It runs again, and only its own cache goes.** The Explorer works by rendering SQL over its source,
so exploring a result is a billed execution, as opening a table is — filtering the stored result
object would be a second engine. Executions are cached by rendered SQL for the session, so without
an eviction exploring a statement after an `INSERT` shows the earlier rows, and so does every filter
re-applied over it. Once the tab exists, `evictSqlSource` removes every cached execution over that
body and no other. Which body an execution read is judged at the **outer** `FROM`, the first line
starting with it: a substring test matched a longer body beginning the same way, and a body holding
this one's whole subquery — the Explorer's own generated SQL, explored again — would have been
billed for a re-run nobody asked for. `removeQueries`, not the catalog eviction's `resetQueries`,
which refetches every observed match: nothing is observed at that moment, because the page holds
its execution back while the hand-off is pending, and removal keeps the eviction from starting an
execution itself if that gate ever moves. At the tab limit nothing is evicted.

**A result whose columns cannot be named is refused whole.** Athena names an unaliased expression
`_col0`, which the outer query cannot refer to, and a join selecting `a.id` and `b.id` returns two
columns called `id` that neither the outer query nor the grid's name-keyed geometry can tell apart.
The control is offered disabled with one sentence saying to add `AS`; offering the tab and refusing
per column would leave some gestures working on it and others not.

**Only SELECT, WITH and VALUES are explorable** — what Trino accepts as a subquery. `SHOW`,
`DESCRIBE` and `EXPLAIN` produce result grids but get no control. The check lives on the Query side
(`isExplorableSql`), which is where the statement is split: the Explorer never needed the lexer the
[SPEC-183 entry](a-saved-exploration-follows-the-flag-that-owns-the-store-not-the-one.md) expected it to, because it receives one statement already classified.

**A `sql` tab remembers its source's columns.** Once a grouping is applied, the execution's columns
are the grouping's, and a `sql` source has no Glue schema to fall back on, so the Grouping panel
listed nothing. The tab records the column list of each ungrouped succeeded execution — judged on
the current execution, never the last-good one a failure falls back to, which may have been grouped
— and persists it; a malformed stored list restores the tab without it.

**Rejected.** Filtering the stored result instead of re-running — a different engine, asked for by
no one. Carrying the statement in the URL — it can be long and quote the user's data, and a URL is
kept in history and logs. Per-column refusals for unnamed columns — a tab half of whose gestures
fail.

## History

### 2026-09-21

- **Settled:** SPEC-242.
