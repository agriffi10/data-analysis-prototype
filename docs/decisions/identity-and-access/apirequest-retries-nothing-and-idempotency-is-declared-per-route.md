---
type: Decision
title: "`apiRequest` retries nothing, and idempotency is declared per route (SPEC-197)"
description: "**Browser-side, `apiRequest` retries NOTHING, under any status**: a 401 is one request, one call of the unauthenticated handler and `SessionExpired`, because the portal server's `/api/` route refreshes the token before it forwards. Idempotency is declared **per route**, never derived from the method, and a path parameter that is not **one segment** is **refused in the browser**. **The client's 50-second timeout sits above the server's worst path**, held by a test that sums the server's own constants."
---

Zero retries under every condition — a 401, a timeout, a 429, a 503, a network failure — asserted as
a `fetch` call count of exactly one. Retrying a 429 amplifies the condition that caused it.

**A 401 is not retried either, since 2026-11-15.** The browser holds no token: the portal server's
`/api/` route attaches the session's ID token and refreshes it first when it is within five minutes
of expiry. So a 401 that reaches the browser means the session is gone or the browser's cookie now
belongs to another user, and nothing the browser could retry would help. `apiRequest` calls the
unauthenticated handler once and returns `SessionExpired`; what the handler does is
`identity-and-access/cognito-tokens-are-held-per-tab-not-per-browser`. The superseded rule gave a 401
one forced refresh and one retry, which was then the browser's only refresh path.

Whether a call may be retried *above* the client is a property of the **route**, declared in the
contract and never derived from the method: a `POST` that resolves a free name is a read, and a `PUT`
that appends is not. `apiRetryPolicy(routeId)` is the only source of a TanStack Query `retry` value
an API-backed hook sets for itself, and the test enumerates the generated table so a route added later
is covered without the test being edited. A hook that sets none takes the query client's default,
which is for reads alone (mutations inherit no retry) and reads the failure's **code**: one more send
for a failure that may pass, none for a refusal that cannot (`AccessDenied`, `NotFound`, an invalid
request, a document too large to read). A route's policy does not read the code, so a hook that takes
it still re-sends a `NotFound`. The reason it is a rule rather than a habit: a failing apply in the
Data Explorer once issued **two** `StartQueryExecution` calls 1.1 s apart, because `retry: 1` had been
set on something that looked like a read and was a billed, stateful action.

**The client's timeout sits ABOVE the server's worst path**, so the server always gives up first and
a client abort always means a genuinely dead connection. A shorter client timeout aborts requests the
server then completes, which for a write is a mutation the user believes failed. Before it forwards,
the `/api/` route may make three store calls (the read, a refresh's compare-and-set write, and the
re-read after losing it) and one token-endpoint call, each bounded, and then it waits 35 seconds for
the API, which itself answers inside API Gateway's 30-second ceiling: 46 seconds in all. So
`TIMEOUT_MS` is 50 seconds, and a test under `src/server/session/` imports the server's constants and
fails if the client's timeout is not above their sum.

## History

### 2026-11-27

- **Changed:** the query client's default retry reads the failure's code. It was a flat one retry,
  so every read that set no policy sent a refusal twice, a second apart.

### 2026-11-15

- **Changed:** SPEC-262 put the browser's calls through the portal server's `/api/` route. The 401
  retry is gone with the browser's tokens, and the timeout moved from the API's ceiling to above the
  server's worst path.

### 2026-08-18

- **Settled:** SPEC-197.
