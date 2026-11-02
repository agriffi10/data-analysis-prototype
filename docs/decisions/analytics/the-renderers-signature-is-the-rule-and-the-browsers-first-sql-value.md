---
type: Decision
title: "The renderer's signature is the rule, and the browser's first SQL value interpolation is two gates wide (SPEC-178)"
description: "`renderExplorationSql(source, query)` takes only those two arguments, so only filter, order and grouping render SQL and visible columns never narrow the projection; a filter value is quoted by `sqlLiteral`, and a bare number passes two gates or is refused."
---

The Data Explorer reduces to one idea: a user's grid gestures are a *description of a query*, and
the app renders that description and runs it. SPEC-178 builds that engine with no route, no grid
and nothing a user can see, because it settles two things that would be expensive to get wrong
after five specs have built on them.

**Filter, order and grouping render SQL; everything else is presentation — and that is enforced by
a PARAMETER LIST, not by discipline.** `renderExplorationSql(source, query)` takes two arguments,
so column visibility, order, pinning, width and SPEC-184's colours and transformers are not merely
documented as unable to change the SQL: they are unreachable from the function that renders it. A
later edit cannot make the projection depend on which columns are visible without changing the
signature, which is a change a reviewer sees. `SELECT *` always follows. The rejected optimization
is recorded rather than left as an apparent inefficiency: narrowing the projection to the visible
columns would cut bytes scanned substantially on Parquet, and would turn un-hiding a column into a
billed, several-second re-run — cost depending on a gesture users read as cosmetic. Predictable
cost wins. A feature-scoped AST-style sweep forbids a second builder; a **repo-wide** one was
specified and is not achievable, since `useTableActions`, `useRunDdl` and `CreateViewDialog` build
real DDL today and `DEFAULT_SQL` is `SELECT 1;` — a sweep exempting three legitimate builders would
prove nothing about the fourth.

**This is the first place the browser interpolates a user-supplied VALUE into SQL, and the escaper
is the Trino/DML one.** Everything the portal built before is either typed into Monaco or assembled
from identifiers already validated against `CATALOG_IDENTIFIER_RE`; a filter value is neither.
`lib/sql.ts`'s `sqlLiteral` **doubles the quote** and is not `cpcommon.ddl.literal`, which
backslashes for Hive — the repo's "two escapers, never confused" note gains its TypeScript half
here, and the failure mode of confusing them is the bad one: no error, just a predicate that
silently never matches. The raw expression bar does **not** relax this and the asymmetry is the one
thing a reader must not get backwards — the bar is the *user's own SQL* and passes through
verbatim, as Monaco's does, while a filter value arrives *from data* and is quoted on their behalf.
A cell containing `O'Brien` filtered by one click is the whole hazard, and it arrives from real
data long before anyone thinks to type it. *(Qualified by SPEC-247: an expression can now also
arrive in a saved view another member of a shared space wrote, so it is not always the viewer's own
SQL. Such a view is held until the viewer runs it — [the SPEC-247 entry](a-saved-exploration-carries-its-view-on-one-comment-line-and-a-shared.md).)* *(Superseded in
part by SPEC-251: the bar is gone. An expression stored before that still passes through verbatim,
read-only, and nothing writes a new one; **is like** quotes its pattern like any other value — the
[SPEC-251 entry](a-filter-is-conditions-and-groups-built-by-pointing-and-the-expression.md).)*

**The spec's own filter model would not have worked, and nothing offline would have caught it.**
`value?: string` with every value quoted renders `WHERE "qty" > '5'`, and Trino does not coerce
varchar to bigint — a *query-time* error, invisible on the CSV-derived tables the Table Builder
makes all-string, surfacing on the first Parquet table. `ColumnFilter` therefore carries an optional
`valueKind`, and `'number'` renders **bare**; the repo's own Trino renderer already does exactly
this (`dqcommon/sql.py` interpolates a count unquoted beside a `_literal_dml`-quoted path). The bare
value is the one thing the renderer does not escape, so what admits it IS the trust boundary, and it
is **two gates**: a bounded charset, which is load-bearing rather than a fast path because `Number`
alone accepts `0x1f`, `0b11` and `Infinity`; and `Number.isFinite`, because a hand-written numeric
grammar is exactly the thing that is subtly wrong — the first one written here tripped
`security/detect-unsafe-regex`, and deferring to the engine's own parser is both safer and shorter.
A value failing either gate is **refused, never quoted as a fallback**, since quoting restores the
type error the kind exists to prevent.

**One execution per distinct rendered SQL, and the failed one is evicted on the way OUT.** The
rendered SQL is the cache key, which makes the cache the cost control: an identical description is a
cache hit, so changing a filter and changing it back is free, and paging *within* an execution
scans no extra bytes. Requiring that a re-applied description **retry** after a failure is the
subtle part — evicting on observing `FAILED`, with an observer still mounted, refetches
immediately, which is start → FAILED → evict → start, an **unbounded loop against
StartQueryExecution** on any permanently-bad statement. The eviction happens in the effect cleanup,
when the statement changes or the hook unmounts. **Be precise about what that loop costs**: AWS does
not bill a FAILED Athena query, so the first cost is the API hammering and the account-wide query
concurrency it consumes — but the same branch covers **CANCELLED**, which *is* billed for whatever it
scanned before it stopped, so a loop over a statement the user keeps stopping bills every pass. A
paired test asserts a SUCCEEDED
execution is *not* evicted, because an unconditional eviction makes every remount a fresh bill and
the failure test alone would still pass.

**A tab's cost ledger is keyed by execution id rather than accumulated**, which makes "a cache hit
adds nothing" true by construction — a re-rendered identical statement resolves to an id already in
the map. A running total would have to *detect* a hit, and a detector can be wrong in the direction
that overcharges. Athena offers no pre-flight estimate, so reporting after the fact is the only cost
signal the feature can give.

**`ExplorationSource` is a union from the outset with only the `table` arm reachable for five
specs.** A saved `.sql` file cannot be reverse-engineered into a table plus filters without a SQL
parser, so SPEC-183's loaded file is a **source**, not a view state; filters, ordering and grouping
compose over either arm without knowing which. Retrofitting the union at 183 would have touched
every spec in between. *(Superseded in part by SPEC-247: a Data Explorer save now also writes the
view state, on one comment line in the same file, and that is what reopens — never the SQL, which is
still not parsed.)*

## History

### 2026-08-13

- **Settled:** SPEC-178.
