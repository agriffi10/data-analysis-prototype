---
type: Decision
title: "`apiRequest` retries nothing, and idempotency is declared per route (SPEC-197)"
description: "**Browser-side, `apiRequest` retries NOTHING**, with one exception: a 401 takes one forced refresh and one retry — the browser's only refresh path, so deleting it signs everyone out at the hour mark with a green suite. Idempotency is declared **per route**, never derived from the method, and a path parameter that is not **one segment** is **refused in the browser** — either spelling would otherwise reach a **sibling route answering 200 with the wrong shape**."
---

Zero retries under every condition — a timeout, a 429, a 503, a network failure — asserted as a
`fetch` call count of exactly one. Retrying a 429 amplifies the condition that caused it.

**Exactly one exception, and deleting it signs every user out at the hour mark with a green suite:**
a 401 triggers one forced token refresh and one retry, and no more. That refresh is the browser's
only token-refresh path. The test that says so is a count — a 401-then-200 sequence issues exactly
two requests, and a 401-then-401 sequence issues exactly two as well.

Whether a call may be retried *above* the client is a property of the **route**, declared in the
contract and never derived from the method: a `POST` that resolves a free name is a read, and a `PUT`
that appends is not. `apiRetryPolicy(routeId)` is the only source of a TanStack Query `retry` value
for an API-backed hook, and the test enumerates the generated table so a route added later is covered
without the test being edited. The reason it is a rule rather than a habit: a failing apply in the
Data Explorer once issued **two** `StartQueryExecution` calls 1.1 s apart, because `retry: 1` had been
set on something that looked like a read and was a billed, stateful action.

**The client's timeout sits ABOVE the function's**, so the server always gives up first and a client
abort always means a genuinely dead connection. A shorter client timeout aborts requests the server
then completes, which for a write is a mutation the user believes failed. The ordering is created by
the function's 29 s against the integration's 30 s ceiling — not, as the spec's constant name
suggested, by a 29-second gateway timeout that does not exist.

## History

### 2026-08-18

- **Settled:** SPEC-197.
