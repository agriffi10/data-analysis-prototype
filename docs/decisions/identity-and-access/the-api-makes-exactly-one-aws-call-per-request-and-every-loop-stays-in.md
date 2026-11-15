---
type: Decision
title: "The API makes exactly ONE AWS call per request, and every loop stays in the browser (SPEC-199)"
description: "**The API's remaining fences live beside it** — `@lambdas/info/planes/api.md` for the plane, this area's other decisions for the rest — and they are traps rather than reference: **no route waits, sleeps or paginates** and no call count grows with the user's data (a small fixed number is fine); the error shape is a machine **CODE** whose wording is chosen client-side; the wire is declared in **Python** and the TypeScript is **generated** from a **closed** vocabulary that never falls back; **`$default` matches OPTIONS**, so the router answers a preflight **before authentication** and only a browser can see that fail; and **no route waits**, every poll and page walk staying in the browser against a **non-raisable** 30-second integration ceiling."
---

> **The heading's literal count was already false when it was written, and is kept because every
> link and ADR row points at it (2026-09-01).** `objects.move` heads, copies and deletes on one
> request, and SPEC-216's multipart create heads then creates. **What this entry actually settles,
> and what `test_api_thinness.py` enforces, is the SHAPE:** no route sleeps, waits, paginates or
> walks a continuation token, and no route's call count grows with the user's data. A small fixed
> number is fine; free-name's is bounded rather than fixed, at `FREE_NAME_MAX_ATTEMPTS`. Read the
> count as "not a loop", not as "not two".

The shape a reader reaches for is *"the API waits for the query"*, and it is wrong twice over. **The
ceiling is computed, not asserted:** an HTTP API's integration timeout is 30,000 ms and is **not
raisable**, so a five-minute query is 10× the budget — the rejected design does not fail at the
margin, it fails always — and it would hold a Lambda open for the duration of a user's query while
doing so. The slowest route on this surface is `athena.results` at a 1000-row page, sub-second.

So the four loops the catalog rides on stayed exactly where they were, unchanged apart from what they
call: `useQueryExecution`'s poll (1.5 s, 5-minute ceiling), `runStatementToCompletion`'s (400 ms × 90),
`useQueryResults`' `NextToken` paging, and `useResultRowCount`'s background walk. `listTables` walks
the API's `nextToken` inside the service, so `useSchema` still gets every table from one call.

> **Changed by SPEC-234:** `useQueryExecution`'s ceiling is now 30 minutes, and it is a verdict on a
> read after it rather than a stop on the clock. Full entry: `docs/decisions/browser/`, *A long query settles at
> the ceiling, judged on a read after it, and says where its results go*.

**The counting rule is the part that is easy to get wrong.** "One botocore call per request" is
unsatisfiable on a cold invocation and satisfiable on the next, because the per-container session
cache makes `sts:AssumeRole` fire on some invocations and not others. The assertion is therefore on
**the service client the route holds** — the one returned by `user_client('athena'|'glue', …)` — and
says nothing about STS. The distinguishing case is `catalog.tables.list`: a server-side `NextToken`
walk would satisfy every behavioural test and quietly make the API a loop over a user-controlled
collection.

**The accepted consequence is stated rather than mitigated.** A five-minute query is ~200 status
requests and a million-row walk ~1000 results requests — the same counts as before, one extra hop
each. They now meet API Gateway account throttling, `apiRequest` never retries a 429, and the walk
already swallows a failed page into `total: null`. No new mechanism was added.

**The one exception in this arc is SPEC-198's free-name route**, and its justification — 999
sequential probes for one gesture — does not generalise to a 1.5-second poll. The sweep that holds
this reads code, not prose: no `time.sleep`, no botocore waiter, no paginator, no `while` over a
continuation token, plant-verified in both directions.

**`$default` matches OPTIONS**, and since SPEC-262 an `OPTIONS` is refused like any unauthenticated request: no browser calls the API, so there is no preflight to answer before authentication (the router answered one until then). The API's remaining fences live beside it, in `lambdas/info/planes/api.md`.

## History

### 2026-09-01

- **Changed:** The settled rule was restated as a shape, no sleep, wait, paginator or data-sized call count, because the heading's literal one call was already false.

### 2026-08-29

- **Settled:** SPEC-199.
