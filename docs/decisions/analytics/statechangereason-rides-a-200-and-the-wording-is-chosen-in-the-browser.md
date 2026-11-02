---
type: Decision
title: "`stateChangeReason` rides a 200 and the wording is chosen in the browser (SPEC-199)"
description: "**A failed query is a 200.** `stateChangeReason` rides the body byte-identical and the browser picks the sentence; enveloping it retires six authored ones at a stroke. Lake Formation denies in **two shapes** — a Glue 403, and an execution that reaches FAILED on a 200 — and a 403 is **never** a re-login. `dataScannedBytes` is `null` while non-terminal, never `0`. The generic sentence is reserved for what a user **cannot** act on, held by a computed `USER_FIXABLE_CODES`."
---

A query Athena refuses is not an error anywhere in the plumbing: `GetQueryExecution` **succeeds** and
the reason arrives as a field. So a FAILED or CANCELLED execution is a **200** with the engine's
string byte-identical on the body — never truncated, never mapped to a code, never merged into
`detail` — and `lib/errorMessages.ts` chooses the sentence.

**This is not in tension with the API answering machine codes** (SPEC-197), and the distinction is
the whole entry: a code describes what happened to the **request**, and `stateChangeReason` is data
about a **query** that the request retrieved successfully. Mapping a failed execution onto an error
envelope is the change that looks most correct, and it retires six authored sentences — unqualified
table, table not found, column not found, Lake Formation permission, still-running, syntax error — the
`FAILED`/`CANCELLED` codes `useExploration` mints, and the last-good-rows fallback, in one move. Every
failed query then says *"Something went wrong. Contact the Administrator."* and nothing looks broken.
**No later spec may move that mapping server-side**; that is SPEC-106 reversed by a route that looked
like it was being helpful.

**Lake Formation denies in two different shapes and both must survive.** A Glue read the caller has
no `DESCRIBE` on raises `AccessDeniedException` → **403**, envelope-shaped, no AWS text in `detail`.
An Athena query the caller has no `SELECT` on does not fail the call at all — the execution reaches
FAILED and the reason names Lake Formation, on a **200**. An implementation that maps every LF denial
to a 403 handles the first perfectly and silently converts the second into an error envelope. A 403
from either is **never** a re-login: collapsing 401 and 403 makes the isolation model present as a
broken session.

**Two related fields are load-bearing and easy to lose.** `dataScannedBytes` and
`engineExecutionTimeMillis` are `null` while an execution is non-terminal, as Athena reports them — a
poll that reports a confident `0` freezes the tab's cost figure at zero. And `outputLocation` must
survive, because the export copies that object and Save results parses it.

**The generic sentence is reserved for what a user cannot act on.** That rule is why
`QuerySyntaxError` exists rather than folding into `InvalidRequest`, and it is held by
`USER_FIXABLE_CODES`, computed from the rules: a code marked user-fixable that resolves to
"contact the administrator" is a contradiction the guard can see.

## History

### 2026-08-29

- **Settled:** SPEC-199.
