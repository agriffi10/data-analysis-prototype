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

**Dependency notes:** none. This spec shares no file with SPEC-271, SPEC-272 or SPEC-273 and can
be built beside any of them.

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

Nothing a user does changes. With many spaces, the last databases' tables reach autocomplete, and
the last spaces' checks reach the list, a little later than the first.

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

A database the user expands in the rail while autocomplete's reads are queued waits its turn
behind them. That is accepted: the wait is bounded by the reads ahead of it, and a second limiter
for the rail would put the total back above four.

#### Acceptance Criteria:

- [ ] Opening Query with twelve usable databases never has more than four schema reads in flight,
      and ends with all twelve databases' tables offered to autocomplete (measured before this
      spec: twelve in flight).
- [ ] A schema read that fails frees its place: the databases behind it still load, and the failed
      one is omitted from autocomplete as today.
- [ ] A database expanded in the rail while reads are queued shows its tables once its read has
      run.
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

- [ ] Leaving Query and returning two minutes after its schemas loaded reads one schema: that of
      the database the rail expands by default (measured before this spec: every database).
- [ ] Returning six minutes after they loaded reads every usable database's schema, at most four
      at once.
- [ ] A DDL statement run two minutes after the schemas loaded re-reads that database's schema at
      once, and autocomplete offers the new table.

### FR-004: The data-quality list reads at most four spaces' indexes at once

#### Description:

`useDataQualityRuns` reads its per-space indexes through a limiter of
`DATA_QUALITY_INDEX_CONCURRENCY` (4), created per query run. Everything else about the list is
unchanged: spaces settle independently, an unreadable space is skipped and logged, and the query
fails only when every space did.

#### Acceptance Criteria:

- [ ] The list over twelve spaces never has more than four index reads in flight, and shows the
      checks of every space that answered, newest first.
- [ ] With one space's read failing for a reason a retry could clear, the list shows the other
      eleven and names that space as unreachable.
- [ ] With every space's read failing, the list shows its error and not an empty history.

---

## Data Model

```ts
// src/lib/limitConcurrency.ts
export function limitConcurrency(max: number): <T>(task: () => Promise<T>) => Promise<T>;

// src/features/catalog/catalog.constants.ts
export const SCHEMA_READ_CONCURRENCY = 4;
export const COMPLETION_SCHEMA_STALE_MS = 5 * 60_000;

// src/features/data-quality/dataQuality.constants.ts (or the feature's existing constants module)
export const DATA_QUALITY_INDEX_CONCURRENCY = 4;
```

## File & Folder Structure

```
apps/portal/src/
├── lib/limitConcurrency.ts                         (+ test)
├── features/catalog/useSchema.ts                   (the shared limiter, autocomplete's staleTime)
├── features/catalog/catalog.constants.ts
└── features/data-quality/useDataQualityRuns.ts
```

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
