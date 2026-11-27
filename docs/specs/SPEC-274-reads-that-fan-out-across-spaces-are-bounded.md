---
type: Spec
id: SPEC-274
title: "Reads That Fan Out Across Spaces Are Bounded"
description: "Bounds the reads the portal starts once per space: opening Query no longer starts a schema read for every database at the same moment, autocomplete's copy of a schema is re-read every five minutes rather than every thirty seconds, and the data-quality list reads at most four spaces' indexes at once."
spec_status: Draft
depends_on: []
arc: render-scope
arc_order: 4
---

**Dependency notes:** none. This spec shares no source or test file with SPEC-271, SPEC-272 or
SPEC-273 and can be built beside any of them; the files every completion ritual edits (the
generated indexes, the component inventory, `docs/testing/owed.md`) are shared, and conflict by
addition only.

## Overview

Two pages start one read per space the user can reach, all at the same moment. Opening Query loads
every usable database's schema so the editor's autocomplete can offer its tables, and the
data-quality list loads every space's index of past checks. Each read is a Lambda invocation behind
the API, and the account's Lambda concurrency is ten, shared with everything else the user and
their colleagues are doing. Measured at `91f97fe60`, opening Query with twelve usable databases
started twelve schema reads at once. A user with enough shared spaces can therefore exhaust the
account's concurrency by opening one page, and the failure shows up somewhere else, as a 503 on an
unrelated request. This spec bounds both fan-outs at four reads in flight, and stops autocomplete
re-reading every schema each time Query is opened more than thirty seconds after the last time.

What a user does is unchanged. Two things they could notice are accepted, by the author at
authoring and not yet ruled on by Andrew: with many spaces, the last databases' tables reach
autocomplete, and the last spaces' checks reach the list, a little later than the first; and a
table a colleague creates reaches autocomplete's suggestions up to five minutes later, though the
rail shows it as soon as it does today.

## Scope

### In Scope

- A limiter, and its use by every read of a database's schema and by the data-quality list.
- How soon autocomplete's observers of a schema query read it again.

### Out of Scope

- **Raising the account's concurrency, or any server-side change.** The API and its Lambdas are
  untouched.
- **What the rail reads.** A collapsed database still reads nothing, and an expanded one is still
  re-read on the app's default thirty seconds.
- **Reads that do not fan out.** A query's status poll, a listing and a single space's index are
  not limited.
- **Cancelling a queued read.** A read that is waiting for a place when its page unmounts still
  runs when its turn comes; its result lands in the cache, as an in-flight read's does today.

---

## Functional Requirements

**This spec is planned with an execution harness, not only a review**
(`docs/process/authoring-a-spec.md`): how many reads overlap is a property of executions, and
cannot be read off the code. The harness is a test double whose every read is a promise the test
settles by hand, with a counter of reads started and not yet settled; each criterion below that
names a number in flight is asserted on that counter's maximum.

### FR-001: A limiter runs a bounded number of tasks at once, in the order asked

#### Description:

`lib/limitConcurrency.ts` returns a function that takes a task and returns its promise. At most
`max` tasks run at once; the rest start in the order they were asked for, each as an earlier one
settles. A task that rejects, or throws before returning a promise, frees its place like one that
resolves, and its rejection reaches its own caller and no other.

#### Acceptance Criteria:

- [ ] Twelve tasks through a limiter of four: the counter's maximum is four, and the fifth starts
      only when one of the first four settles.
- [ ] Tasks start in the order they were asked for.
- [ ] A rejected task's caller receives the rejection, and the next waiting task starts.
- [ ] A task that throws synchronously rejects its caller and frees its place.
- [ ] After every task has settled the limiter holds nothing, and a thirteenth task starts at
      once.

### FR-002: Schema reads share one limit of four

#### Description:

Every read of a database's schema, from the rail, from autocomplete and from the Data Explorer's
source picker, runs through one module-level limiter of `SCHEMA_READ_CONCURRENCY` (4). A schema
read is one task: it asks Glue for the database and then for its tables, a page at a time, each
call after the last, so one task has one request in flight. Four tasks are therefore at most four
Lambda invocations, under half the account's ten.

On the editor's surface a database expanded in the rail costs no read of its own: the rail and
autocomplete observe the same query, so the rail joins the read autocomplete already asked for.
Below `tablet`, where autocomplete reads nothing, the rail's reads are the only ones and take
their places like any other. `useRefreshLink` and the Data Explorer's `useSourceColumns` and
`SourcePicker` read through the same function, so they are limited with no change of their own.

The limiter is module-level, so it outlives a test. The harness settles every read it started
before a test ends, and a test that leaves one pending fails.

#### Acceptance Criteria:

- [ ] Opening Query with twelve usable databases never has more than four schema reads in flight,
      and ends with all twelve databases' tables offered to autocomplete (measured before this
      spec: twelve in flight).
- [ ] A schema read that fails frees its place: the databases behind it still load, and the failed
      one is omitted from autocomplete as today.
- [ ] `invalidateSchema` still re-reads a database's schema, and still tells every registered
      listener.

### FR-003: Autocomplete re-reads a schema after five minutes, not thirty seconds

#### Description:

Autocomplete's observers of the schema queries take a `staleTime` of `COMPLETION_SCHEMA_STALE_MS`
(five minutes). The rail's observer keeps the app default, and a DDL statement still invalidates
the query for both. A suggestion list that is up to five minutes behind a colleague's new table
costs nothing a user can be misled by: the rail, which is what shows a database's tables, is
unchanged.

The criteria below are decided on a query client with the production defaults
(`lib/queryClient.ts`), not the test harness's, whose zero `staleTime` and `gcTime` would re-read
everything, and on a fake clock.

#### Acceptance Criteria:

- [ ] Leaving Query one minute after its schemas loaded and returning at two minutes reads one
      schema: that of the database the rail expands by default (measured before this spec: every
      database).
- [ ] Leaving at four minutes and returning at six reads every usable database's schema, at most
      four at once. The entries are still cached at six minutes, since the client keeps an
      unobserved query for five, so it is the `staleTime` that causes the re-read.
- [ ] A DDL statement run two minutes after the schemas loaded re-reads that database's schema at
      once, and autocomplete offers the new table.

### FR-004: The data-quality list reads at most four spaces' indexes at once

#### Description:

`useDataQualityRuns` reads its per-space indexes through one module-level limiter of
`DATA_QUALITY_INDEX_CONCURRENCY` (4). Module-level, not one per run of the query: **Refresh**
starts a second run while the first one's reads are still in flight, and a limiter per run would
allow eight. Everything else about the list is
unchanged: spaces settle independently, an unreadable space is skipped and logged, and the query
fails only when every space did.

#### Acceptance Criteria:

- [ ] The list over twelve spaces never has more than four index reads in flight, and shows the
      checks of every space that answered, newest first.
- [ ] With one space's read failing for a reason a retry could clear, the list shows the other
      eleven and names that space as unreachable.
- [ ] With every space's read failing, the list shows its error and not an empty history.
- [ ] **Refresh** pressed while the first run's reads are in flight never has more than four index
      reads in flight across both runs.

---

## Data Model

```ts
// src/lib/limitConcurrency.ts
export function limitConcurrency(max: number): <T>(task: () => Promise<T>) => Promise<T>;

// src/features/catalog/catalog.constants.ts
export const SCHEMA_READ_CONCURRENCY = 4;
export const COMPLETION_SCHEMA_STALE_MS = 5 * 60_000;

// src/features/data-quality/dataQuality.constants.ts (new)
export const DATA_QUALITY_INDEX_CONCURRENCY = 4;
```

## File & Folder Structure

```
apps/portal/src/
├── lib/limitConcurrency.ts                              (+ limitConcurrency.test.ts)
├── features/catalog/useSchema.ts                        (the shared limiter, autocomplete's staleTime)
├── features/catalog/catalog.constants.ts
├── features/query/schemaReads.test.tsx                  (new: FR-002 and FR-003, through the Query workspace)
├── test/deferredReads.ts                                (new: the hand-settled reads the harness counts)
├── features/data-quality/dataQuality.constants.ts       (new)
├── features/data-quality/useDataQualityRuns.ts
└── features/data-quality/dataQualityRunsFanOut.test.tsx (new: FR-004)
```

The Query-level cases go in a new file under `features/query/`, since lint refuses a file under
`features/catalog/` that imports the workspace, and so this spec edits none of the Query
workspace's existing suites or `src/test/queryWorkspaceSupport.tsx`, which are SPEC-272's while it
is in flight. The deferred reads have a file of their own for the same reason.

## Implementation Phases

### Phase 1: The limiter and its harness

- `lib/limitConcurrency.ts` with FR-001's suite, and the deferred-read test double the other
  requirements count with.

### Phase 2: Schema reads and autocomplete's staleness

- The module-level limiter around the schema read (FR-002), and the observers' `staleTime`
  (FR-003), with the baseline of each recorded before the change.

### Phase 3: The data-quality list, close-out

- The list's limiter (FR-004).
- Completion ritual: the delivery doc carries the before and after maxima, each anchored to its
  commit.
