# Completed Spec — SPEC-178: The Exploration Model, the SQL Renderer and the Execution Cache

## What was completed?

The Data Explorer's engine, ahead of every UI spec: no route, no page, no grid, nothing a user
can see. It settles the two things that would have been expensive to get wrong later — the shape
of an exploration, and the first place in this codebase where the browser interpolates
user-supplied **values** into SQL.

- **`lib/sql.ts`** — `sqlLiteral` (Trino/DML: doubles the quote) and `sqlIdentifier`, with the
  DML/DDL distinction documented at the definition. In `lib/` because they are language rules,
  not feature domain.
- **`features/data-explorer/`** — the `Exploration` model with `ExplorationSource` as a union
  from the outset (only the `table` arm reachable until SPEC-183), `renderExplorationSql`,
  `useExploration`, `useExplorationTabs`, `explorerKeys` rooted at `['data-explorer']`.
- **The one-builder sweep**, which was verified by committing a violation and watching it fail.

## The central rule is structural, not documented

`renderExplorationSql(source, query)` takes two parameters. Column visibility, order, pinning,
width — and SPEC-184's colours and transformers — are not merely *documented* as unable to change
the SQL; they are unreachable from the function that renders it. A later edit cannot make the
projection depend on which columns are visible without changing the signature, which is a change
a reviewer sees.

`SELECT *` always follows from that. The rejected optimization, recorded so a future reader finds
the reasoning rather than an apparent inefficiency: narrowing the projection to the visible
columns would cut bytes scanned substantially on Parquet, and would turn un-hiding a column into
a billed, several-second re-run. Cost would then depend on a gesture users read as cosmetic.
Predictable cost wins.

## The spec's filter model would not have worked, and the failure was invisible

As specified — `value?: string`, every value through `sqlLiteral` — a filter on a numeric column
renders `WHERE "qty" > '5'`. Athena is Trino and Trino does not coerce: that is a query-time
error, not a comparison. Nothing offline catches it, and it stays hidden on CSV-derived tables,
which the Table Builder makes all-string. It would have surfaced on the first Parquet table, at
which point SPEC-180/181/182 would already have been built on the model.

`ColumnFilter` gains an optional `valueKind: 'string' | 'number'`; `'number'` renders bare.
The repo's own Trino renderer already does exactly this (`dqcommon/sql.py` interpolates a count
unquoted beside a `_literal_dml`-quoted path), so this is the TypeScript half of a rule the
project already had.

**The bare value is the one thing the renderer does not escape, so what admits it IS the trust
boundary, and it is two gates.** The charset is load-bearing rather than a fast path — `Number`
alone accepts `0x1f` (31), `0b11` (3) and `Infinity` — and `Number.isFinite` bounds the grammar,
because a hand-written numeric regex is exactly the thing that is subtly wrong. The first one
written here was: it tripped `security/detect-unsafe-regex`, and rewriting it around the engine's
own parser is both safer and shorter. A value failing either gate is **refused, never quoted as a
fallback** — quoting would restore the type error the kind exists to prevent.

## The asymmetry the feature must not get backwards

The raw `expression` is composed **verbatim**; a filter value is **quoted**. The expression is
the user's own SQL, exactly as Monaco's buffer is. A filter value arrives *from data* — a cell
containing `O'Brien`, filtered by one click — and the app is quoting on the user's behalf.

A test pins it by rendering the *same string* both ways and asserting the two differ, so the
distinction is asserted rather than described.

## Three decisions about cost, one of which review caught

**A failed execution is evicted on the way OUT.** FR-006 AC4 wants a re-applied description to
retry, but evicting on observing `FAILED` — with an observer still mounted — refetches
immediately: start → FAILED → evict → start, an **unbounded loop against StartQueryExecution** on
any permanently-bad statement. The eviction happens in the effect cleanup, when the statement changes
or the hook unmounts, and coming back to it retries. **What the loop costs, precisely**: AWS does not
bill a FAILED query, so the first cost is the API hammering and the query concurrency it consumes —
but the branch also covers **CANCELLED**, which *is* billed for what it scanned before stopping. A
paired test asserts a SUCCEEDED execution is *not* evicted, because an unconditional eviction
would make every remount a fresh execution and the failure test alone would still pass.

**`gcTime` is as load-bearing as `staleTime`, and omitting it made FR-006 AC2 a five-minute
promise.** Found in review. The hook set `staleTime: Infinity` but no `gcTime`, and neither does
`lib/queryClient.ts` — so production got TanStack's 5-minute default. Changing a filter detaches the
previous statement's observer and starts its GC timer; apply a filter, explore for six minutes,
remove the filter, and AC2's "cache hit" is a second execution and a second bill. Worse, the test
that was supposed to pin the behaviour overrode `gcTime` on its own client with a comment calling it
"a reason production never has" — production had exactly that reason, on a timer. The hook now sets
`gcTime: Infinity` and the test sets no defaults at all, so it exercises the hook's own
configuration. **Verified by deleting the line**: the round trip then mints `exec-3`.

**A tab's cost ledger is keyed by execution id, not accumulated.** FR-007's "a cache hit adds
nothing" is then true by construction: a re-rendered identical statement resolves to an id
already in the map, so recording it again changes no total. A running sum would have to *detect*
a cache hit, and a detector can be wrong in the direction that overcharges.

## Verification

All four gates green locally **by exit code**: `format:check`, `lint`, `build`, vitest `0` at
**2228 tests / 99 files** (2148 / 94 on `origin/main` — 80 new across five files), and
`npx vitest run --coverage` `0` at **93.16 / 89.02 / 92.51 / 94.89** against the SPEC-150 floors
of 91/86/89/93. No floor lowered.

**The one-builder sweep was verified by violating it**, not by reading it: appending an
`ORDER BY` template literal to `exploration.ts` reddened it (`expected [ './exploration.ts' ] to
deeply equal []`), and reverting restored green. It carries a guard-the-guard, because a sweep whose
regex or comment-stripping silently stops matching passes forever — and, after review, a non-empty
assertion on the glob and a **recursive** `./**/*` pattern. The flat `./*` passed with a violating
`components/Bad.ts` in place; every feature in the repo is flat today, so it would have gone quiet
exactly when SPEC-179/180 put a grid component in a subdirectory.

**The layering rule was exercised against real files for the first time.** SPEC-176 pre-registered
`src/features/data-explorer/**` before the directory existed; this is the first spec to put files
under it. Five directions, each mutation reverted:

| Direction | Written as | Required | Observed |
|---|---|---|---|
| `data-explorer` → `query` | `'../query/useQueryTabs'` | refuse | refused |
| `query` → `data-explorer` | `'../data-explorer/explorerKeys'` | refuse | refused |
| `saved-queries` → `data-explorer` | `'../data-explorer/explorerKeys'` | refuse | refused |
| `data-explorer` → `catalog` | `'../catalog/catalog.types'` | permit | permitted |
| `data-explorer` → `saved-queries` | `'../saved-queries/savedQueries.types'` | permit | permitted |

**Nothing live is owed.** The spec adds no infra, no IAM and no AWS call the portal did not
already make — `StartQueryExecution` / `GetQueryExecution` / `GetQueryResults` against the
existing workgroup, results in the already-granted `{username}/athenaresults/` prefix.

**User-facing docs sweep: nothing to do, recorded explicitly.** No file under `features/help/`
changed and no wording in `lib/errorMessages.ts` changed — nothing user-facing ships, which is
the spec's own point. SPEC-179 is the first surface and the first help entry.

## Review findings, all taken

A fresh-context review probed the injection surface exhaustively — enumerating every string the
charset admits up to length 7 (50,544 of them) against a strict decimal grammar, with zero
divergences, plus unicode digits, full-width characters, every whitespace form and `0x`/`0b`/`0o`
— and found **no hole**. It confirmed the `cpcommon.ddl.literal` transcription is byte-faithful and
re-verified the sweep by violating it itself. Seven findings, all applied:

- **`gcTime` (above)** — the one that would have cost real money.
- **The `sql` arm composed on one line.** A saved query ending in a `--` comment put the closing
  paren and the alias inside the comment; a trailing `;` broke it the same way. Now `(\n<body>\n)`.
  Worth fixing here rather than in SPEC-183, whose scope is refusing multi-statement and
  non-`SELECT` files — a reader will assume the *renderer* handles composition.
- **The persistence validator checked shape, not renderability.** A stored filter with an
  unrecognised operator reached the renderer as `OPERATOR_SQL[op] === undefined` and emitted
  `"a" undefined 'x'` — invalid SQL sent to `StartQueryExecution` rather than refused; a `grouping`
  of `{}` threw a raw `TypeError` instead of an `ExplorationRenderError`; and an unchecked ledger
  value broke the never-NaN invariant FR-007 AC4 exists to hold, from the only untrusted input this
  model has. FR-008 AC3's "never partially applied" was honoured throughout — *usable* is a
  different property from *well-shaped*, and it is the one that matters here.
- **`openTab` could return an id for a tab that was never created.** The cap was checked against the
  render's state, so three opens two below the cap each saw room and each returned an id while two
  tabs appeared — the caller would believe it opened three and raise no cap dialog. Now a
  synchronous counter decides the return value while the updater stays the authority.
- **`nextExplorationNumber` was dead state** — written, persisted, validated, typed with a
  rationale, never read, and incremented on labelled opens too, so the first consumer would have
  started at the wrong number. Removed. If SPEC-179 wants "Exploration N" labelling it should add it
  deliberately; every tab today takes its name from its source.
- **The sweep's glob (above).**
- **A test whose name was not what it asserted** — "recovers once the description becomes renderable
  again" started from a description that rendered fine, so `error` was never truthy and the
  recovery was never exercised. It now starts from the grouping/ordering refusal.

**One finding was declined, deliberately.** FR-005 AC2 says each side of the `WHERE` is
parenthesized; a *single* filter renders unparenthesized (`"status" = 'open' AND (a OR b)`). That is
safe — one rendered filter is an atomic comparison containing no lower-precedence operator — and the
test pins the exact output. Recorded here rather than changed.

**And one framing was wrong across four documents.** The failed-execution eviction was justified as
preventing a "BILLING LOOP". AWS does **not** bill a failed Athena query, and an `ORDER BY` on a
non-grouped column is rejected at analysis having scanned nothing. The design is unchanged and still
right — an unbounded `StartQueryExecution` loop is a real hazard, and the same branch covers
**CANCELLED**, which *is* billed for what it scanned before stopping — but the justification now says
what is true. Corrected in the code comments, `decisions/`, the inventory and `CLAUDE.md`.

## Notes for the next spec

- **`ExplorationRenderError` reaches `useExploration`'s `error` field.** Its message names the
  offending column and is **operator text** — SPEC-106 forbids rendering it. SPEC-181/182 must
  refuse the gesture before it becomes a description, and treat a render refusal as a bug
  surfaced, not a message to show.
- **`aggregateAlias` is exported for SPEC-182.** The grouping panel must label a column with the
  name the SQL actually emits; a second naming scheme at the view disagrees with the result set
  the moment either changes.
- **`valueKind` needs a producer.** SPEC-181 picks it from the column's Glue/Athena type — the
  types are already on `QueryColumn` and `GlueColumn` from `features/catalog/`. Left unset,
  a filter quotes, which is correct for a string column and wrong for every other.
- **`useExplorationTabs` starts with NO tabs**, unlike `useQueryTabs`' seeded "Query 1": an
  exploration needs a source and there is none to guess. SPEC-179 owns the empty state.
- **The cap dialog is owed.** `openTab` returns `null` at `EXPLORATION_TABS_MAX`; nothing renders
  that refusal yet.
