---
type: Decision
title: "An execution id is a claim, and every route that names one proves it first (SPEC-232)"
description: "**An execution id is a CLAIM, not an authorization.** Athena authorizes by workgroup and there is one, so every route that names an execution proves it is the caller's **first** (its recorded output location under the caller's own `user_results_prefix`) before it answers or acts. Results is included, because S3 guards the rows but not the state. An unknown id and a foreign one get **one 404 body**, and the span says which. A route that skips the proof passes every test that drives only the caller's own execution, which is why the guard is derived from the contract. **A workgroup that enforces its own result location makes every one of them 404** for every user's own queries, so the proof moves with the location."
---

Athena authorizes `GetQueryExecution`, `GetQueryResults` and `StopQueryExecution` by
**workgroup**, and there is one, so the per-user role reaches any execution whose id it holds. SPEC-199 recorded that as an exposure owed a spec, on the premise that
closing it needs an execution→owner record that does not exist. **The premise was false.** Every
query the API starts writes under the caller's own `user_results_prefix`, and Athena records that
location on the execution. Two measurements back that. Through the API, SELECT, SHOW, EXPLAIN,
DESCRIBE, the table and view DDL (create, show-create, drop) and CTAS all record it under the prefix
they were given. From the operator account, a `SELECT 1` already carries it while QUEUED, and an
UNLOAD records it under its prefix, not under its `TO`. Results-conversion already proved ownership
from it (SPEC-221). The location IS the record.

**The proof is one predicate and one helper.** `cpcommon.results.owned_results_key` (the prefix,
plus no dot segment) is shared by results-conversion and the API. `_owned_execution` wraps it with
one `GetQueryExecution` on the route's own client, and status, results, stop and the row count call it before any
other Athena call; a later route that names an execution is held to the same by the guard. An unknown id and a foreign execution get **one 404 body**. The unknown
case is Athena's `InvalidRequestException`, which a malformed id raises too. `detail` reaches the
body, so there is exactly one string, and the span records which case it was in
`execution_ownership`, because a refusal's reason belongs in the log.

**Results takes the proof even though S3 guards its rows.** Measured before the change: a finished
foreign execution answered 400, like an unknown id, because Athena wraps the S3 denial. But a
foreign execution still RUNNING answered 409, which told a holder of the id that its owner's query
was still going. That is why ownership is checked before state, on every route. It also means the
ownership of results no longer rests on the S3 policy, which the client transition moves.

**"The caller's" means written into the caller's own results folder, not started by the caller.** A
plane's statement run into a user's personal space passes that user's proof, and the harm stays
inside her own space. A shared space's plane statements write to the shared-space bucket, which the
proof never accepts.

**Two consequences are stated rather than mitigated.** First, a workgroup that ENFORCES its own
result location makes every execution route answer 404 for every user's own queries. The proof has
to move with the location, in `cpcommon.results`. Second, the same answer holds only within the
portal workgroup. An id from AWS's `primary` workgroup gets IAM's 403, because the per-user role has
no grant there, and mapping that 403 to 404 would make a broken grant read as "not found" on every
poll.

**Do NOT** build an execution-to-owner table, give the guard an exemption, or fold `AccessDenied`
into `NotFound`. The guard derives its population from the contract, and a placeholder spelled
other than `{queryExecutionId}` fails it.

A route that skips the proof passes every test that drives only the caller's own execution, which is why the guard is derived from the contract.

## History

### 2026-09-13

- **Settled:** SPEC-232.
