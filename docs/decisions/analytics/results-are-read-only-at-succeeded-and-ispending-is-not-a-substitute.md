---
type: Decision
title: "Results are read only at SUCCEEDED, and `isPending` is not a substitute (2026-08-16)"
description: "**Results are read only at `SUCCEEDED`.** A too-early `GetQueryResults` reached users as a generic \"contact the administrator\"; the API now answers **409 `QueryNotFinished`**, classified by Athena's **message** — the same `InvalidRequestException` is a malformed query at submit, and a name-keyed mapper passes any test exercising one at a time. The client gate is **kept**, and asserts on the **CALL**: with the 409 in place the screen looks right either way. The values picker's listing is started with `fetchQuery` and **never observed**: an eviction's `resetQueries` refetches whatever is observed, which for a listing is a bill nobody asked for."
---

**Found by running the live-check script against deployed prod, not by review.** Opening a table in
the Data Explorer occasionally showed *"Something went wrong. Contact the Administrator."* on an
ordinary first load.

`ExplorationResultsRegion` handed `useQueryResults` the execution id the moment
`StartQueryExecution` returned, with no gate on the query having finished. `GetQueryResults` against
a QUEUED execution is **400 `InvalidRequestException` / `INVALID_QUERY_EXECUTION_STATE`, "Query has
not yet finished"** — a name in no `CODE_RULE` whose message matched no `MATCH_RULE`, so
`toUserMessage` returned the **generic fallback**. The most alarming sentence the app owns, for a
transient race of our own making.

**`useQueryResults` already documented the contract** — "a pager over a **succeeded** query's
results" — and cannot enforce it, because it is handed an id and never sees the state. So the
contract is kept at the caller, and the caller is now the only place it can be broken.

**`isPending` looks like the obvious gate and is wrong, which is the part worth carrying.** Between
`StartQueryExecution` resolving and the FIRST poll landing, `state` is still `null`, so
`isPending`'s `state !== null && !isTerminalState(state)` clause is *already false*. That window is
exactly where the race lived: gating on `isPending` leaves the bug in place while looking fixed.
The region therefore takes `state` as a prop.

**It read as intermittent, and the reason generalises.** The race fired on **every** load; what
varied was whether TanStack's `retry: 1` re-asked before or after the query finished. A bug that
self-heals on retry presents as flaky and hides in exactly the place a rendering assertion would
look — so **the guard asserts on the CALL, not the screen**, and was verified by reverting the gate
(`expected getQueryResults to not be called at all, but actually been called 1 times`).

**The mapping rule is defence in depth and is matched on the MESSAGE, never the name.**
`InvalidRequestException` is also the name for a rejected MALFORMED_QUERY, and a `code` rule
outranks every message rule — keying on the name would have turned a rejected-at-submit syntax error
into "still running". (An execution that reaches FAILED arrives as `code: 'FAILED'` and was never at
risk.) Rule ordering is **not** load-bearing; the two regexes are disjoint, measured.

**`QueryWorkspace` was never affected** — `displayedResultTab` is null unless the batch is done, and
result tabs are only pushed at SUCCEEDED.

**Two consequences left standing.** While a statement runs the status line now says **"Running…"**
where it said "Loading rows…" — the old text was wrong, and wrong *because* the app really was
fetching rows then. And a query outliving `MAX_POLL_DURATION_MS` (5 min) now shows an indefinite
"Running…" rather than a permanent wrong error banner; neither self-heals, and the behaviour is
unspecified.

> **Superseded by SPEC-234** for the second consequence: a query outliving the watch's ceiling, now
> 30 minutes, settles with a warning that says where its results go, and no longer shows an
> indefinite "Running…". Full entry: `docs/decisions/browser/`, *A long query settles at the ceiling, judged on
> a read after it, and says where its results go*.

**EXTENDED by SPEC-199, when the API landed in this path.** The ambiguity that forced a message rule
in the browser is now resolved at the one layer holding the message: the route classifies Athena's
`InvalidRequestException` **by its text** and answers **409 `QueryNotFinished`** for a too-early read
and **400 `QuerySyntaxError`** for a statement refused at submit. Three things follow, and each is a
place a careful implementation goes wrong.

- **The client rule becomes a `code` rule** — the first time this one could be. A code rule outranks
  every message rule, which is what made the name-keyed version unsafe before and makes this version
  stronger. The old `invalid_query_execution_state|query has not yet finished` match rule is deleted,
  and the sentence is asserted byte-identical so no wording moved.
- **The caller-side gate is KEPT, and its test asserts on the CALL rather than the screen.** With the
  409 mapping in place, removing the gate produces a *correct-looking* "still running" message
  instead of the old alarming one — so a rendering assertion cannot fail any more. The assertion is
  **zero** results requests while the state is `QUEUED` or `RUNNING`. `useResultRowCount` is gated by
  a different mechanism and deliberately so: it reads no state, and its walk is stopped by
  `hasResultSet` — columns having arrived — which is a consequence of a succeeded execution rather
  than a reading of one.
- **Mapping by exception name still passes any test that exercises one case at a time**, which is
  exactly how the original defect survived; the malformed-query counter-case sits in the same file
  for that reason.

## History

### 2026-08-16

- **Settled:** entered the register.
