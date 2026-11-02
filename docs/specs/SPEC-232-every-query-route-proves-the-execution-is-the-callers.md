---
type: Spec
id: SPEC-232
title: "Every Query Route Proves the Execution Is the Caller's, Because an Execution Id Is a Claim"
description: "Makes the API's query status, results and stop routes verify that the Athena execution belongs to the caller, answering unknown and foreign ids identically, so one user cannot read or stop another's query."
spec_status: Completed
depends_on: [SPEC-199, SPEC-220, SPEC-221]
---

## Overview

The Query workspace and the Data Explorer follow a query by its Athena execution id. They poll its
status, read its results and can stop it, each through an API route that names the id in its path.
Athena authorizes those calls by **workgroup**, and this deployment has one shared workgroup. So any
signed-in user holding someone else's execution id can stop that query, and can read its state, the
bytes it scanned, where its results are stored, and Athena's failure text, which routinely quotes the
owner's own cell values.

SPEC-199 recorded this as a pre-existing exposure owed a spec, on the premise that closing it needs
an execution-to-owner record that does not exist. **That premise is false.** Every query the API
starts writes its results under the caller's own results prefix, Athena records that location on the
execution, and results-conversion already proves ownership from it (SPEC-221).

This spec makes status, results and stop prove the execution is the caller's before they answer or
act. Within the portal's workgroup, an id Athena does not know and an id belonging to someone else
get the same answer, so the API cannot be used to ask whether an execution exists. Nothing a user
sees changes, because the browser only ever asks about its own executions.

### What was checked, and how

All readings are from 2026-09-10.

- **Where execution ids come from.** In the browser, every id that reaches status, results or stop
  comes from the response to the same user's own `POST /v1/queries`, in the same page load:
  - the Query workspace's runs, held in memory;
  - the Explorer's, cached in memory for the session with no persister (sign-in is a Hosted UI
    redirect, so the cache cannot carry across users);
  - the DDL helpers, `runStatementToCompletion` and `getTableDdl`.

  Query history re-opens and re-runs by SQL. Its stored id is used only as a React key and to match
  an entry when updating it, and is never polled. Saved explorations store SQL. Deep links carry a
  space, database, table or request id, never an execution id. No notification, and nothing in
  table-builder, table-share, data-quality, shared spaces or saved queries, carries one.
- **Where queries are started, and where they write.** The API's `start()` is the browser's only way
  to start a query, and it always writes under `user_results_prefix(<user-space>, <verified
  username>)`, which is `s3://<user-space>/<username>/system_settings/athenaresults/`. The planes
  start their own queries (table-builder, table-share, data-quality) under a space root's results
  folder, in the same workgroup, and none of their ids reaches the browser. Before the API existed,
  the browser passed the same per-user shape, `{username}/athenaresults/`. SPEC-220 moved it under
  `system_settings/` on 2026-09-08.
- **The workgroup does not override the client.** On the live workgroup, `dat-prod-portal-wg` has
  `EnforceWorkGroupConfiguration: false`. Its default location, `s3://dat-prod-athena-admin/fallback-results/`,
  is under no user's prefix, so an execution started without a location can never pass the proof.
  The account's only other workgroup is AWS's `primary`, and the per-user role has no Athena grant
  on it.
- **The location is on the execution from the moment it is queued.** This had to be measured
  rather than inferred, because two browser paths do not retry a refused status:
  `runStatementToCompletion` makes its first status call straight after the start and returns on
  the first failure (View DDL, Drop, Create view), and a halted multi-statement run calls `void
  stopQuery(nextId)` within milliseconds of starting the next statement. Through the API, QUEUED
  cannot be caught, because the Lambda hop outlasts it. So the operator account started four
  `SELECT 1` executions and read each in the same process. Every one of the eight QUEUED reads
  already carried `OutputLocation`, both with the workgroup's default location and with a
  client-supplied one (`…/spec232-probe/<id>.csv`).
- **Every statement shape records a location under the prefix it was given.** Started through the
  API as `agriffith`: a SELECT records `<prefix><id>.csv`. `SHOW TABLES`, `SHOW DATABASES`, `SHOW
  CREATE TABLE`, `EXPLAIN`, `DROP TABLE` and a FAILED `DESCRIBE` all record `<prefix><id>.txt`, and
  so do the three view statements the browser runs through its non-retrying helper — `CREATE OR
  REPLACE VIEW`, `SHOW CREATE VIEW` and `DROP VIEW`, each from its first poll. A CTAS records
  `<prefix>tables/<id>`. A different measurement, run by the operator rather than through the API:
  an UNLOAD records `<prefix><id>`, even though its data goes to its `TO` location. SPEC-231's
  session read the same field on a RUNNING execution and on one that failed at planning.
- **The exposure is live.** The operator started an execution whose output sits outside every
  user's prefix, in the portal workgroup. Asked for it, `agriffith`'s status answered **200**, with
  its state and its admin-bucket output location.
- **Results content is already the owner's alone, but its state is not.** `GetQueryResults` reads
  the result object with the caller's credentials, and the per-user role reads the user-space
  bucket only under its own `${aws:PrincipalTag/username}/` (`UserPrefixObjects` in
  `infra/modules/data/policies/portal-role-permissions.json.tftpl`, plus the `athenaresults` grant
  in `infra/modules/analytics/policies/portal-role-analytics.json.tftpl`). Measured against the
  operator's executions: a finished foreign execution answers **400 `InvalidRequest`**, the same as
  an unknown id, because Athena wraps the S3 denial. A foreign execution that is **still running**
  answers **409 `QueryNotFinished`**, so today results tells anyone holding an id whether its
  owner's query is still going. `GetQueryExecution` and `StopQueryExecution` never touch S3, and
  that is the rest of the gap.
- **What an unknown or malformed id gets today.** As `agriffith`, a random UUID gets **500
  `InternalError`** from status (it does not classify Athena's `InvalidRequestException`), **400
  `InvalidRequest`** from results, and **200 `{}`** from stop. A 129-character id, an encoded space
  and a one-character id each raise the same `InvalidRequestException` on status.

### Decisions

- **status answers 404 for a foreign execution, and for an unknown one.** Both answer `404
  NotFound` with one shared `detail`, because `detail` reaches the body. The unknown case used to be
  a 500, which blamed the server for the caller's id. The proof is the status read itself, since
  `GetQueryExecution` already returns the output location, so status stays at one call.
- **stop checks first**, at the cost of one `GetQueryExecution`, which is free and scans nothing.
  SPEC-199's thinness rule permits a fixed second call; what it forbids is a call count that grows
  with the user's data. There is no race between the check and the stop, because an execution's
  recorded output location is fixed when it starts. An unknown id and a foreign one both answer 404,
  where an unknown id used to answer 200. No screen changes: the browser calls `stopQuery` only as
  `void stopQuery(...)` and discards the result. The caller's own already-finished execution still
  answers 200, as today.
- **results checks first too**, even though S3 already keeps its content from anyone else. There
  are three reasons, and each would be enough on its own:
  - Today it tells a holder of someone else's id whether that query is still running (409 against
    400, measured above). With the proof in front, the answer that says nothing about existence
    holds on every route, not two of three.
  - The guard (FR-005) needs no exemption. An exemption is where the next route would hide.
  - Results stop resting on the S3 policy, which is exactly what the client transition moves.
    `docs/transition_plan.md` calls query results "the part most likely to move".

  The cost is the same one free call per page. Until SPEC-231's browser phase moves the total row
  count onto its own route, the status bar's row-count walk still fetches every page of a result,
  so it pays that call on every page: latency, not a refusal.
- **The same answer holds within the portal workgroup, not across the account.** The per-user role
  has no Athena grant on AWS's `primary` workgroup, so an id from there gets IAM's 403 where an
  unknown id gets 404. That is stated, not closed. Only an operator runs queries there, and those
  ids reach no user. Mapping the 403 to 404 would make a broken grant on the portal workgroup read
  as "not found" on every query.
- **The refusal's reason goes to the log.** The body is identical for an unknown id and a foreign
  one, so the span carries the difference instead: `execution_ownership` is stamped `unknown` or
  `foreign` on a refusal. That keeps a cross-user attempt attributable, as SPEC-199's `actor` and
  `execution_id` made a cross-user read, and it is where `errors.py` says a refusal's reason
  belongs.
- **"The caller's" means written into the caller's own results folder, not started by the caller.**
  A plane's statement run into a user's personal space (table-builder DDL, a table share to them,
  data-quality's temporary tables) writes there too, and it passes that user's proof. No API
  response carries those ids. A user can still find them by listing her own results folder, and
  could then read or stop that statement. The harm stays inside her own space, and she can already
  read the folder and its objects at S3. A plane's statement in a **shared** space writes to the
  shared-space bucket, which the proof never accepts, so no member can reach another member's.
- **One predicate, and one helper around it.** The prefix-and-dot-segment test becomes
  `cpcommon.results.owned_results_key`, beside `user_results_prefix`, and results-conversion's copy
  moves onto it. The API's `_owned_execution` wraps it with the one Athena read, on the client the
  route already holds (`identity.user_client` builds a fresh boto3 client on every call).
  SPEC-231's row-count route, drafted in parallel, calls the same helper, with the names and
  signatures below agreed between the two sessions. Whichever spec merges first defines it, and
  the other rebases onto it.
- **Ownership is checked before state.** A foreign execution that is still running answers 404, not
  409. Otherwise a caller holding the id would learn whether its owner's query is still going.

## Scope

### In Scope

- `cpcommon.results.owned_results_key`, with results-conversion validate-authorize moved onto it and
  its behaviour unchanged.
- `_owned_execution` in `lambdas/api/routes/athena.py`, called first by `status`, `results` and
  `stop`.
- A guard over every contract route whose path names `{queryExecutionId}`.
- Every statement of the superseded premise, rewritten in code or marked in place in docs: the route
  and test docstrings, SPEC-199's spec and delivery doc, the catalog inventory's `stopQuery` row,
  the exposure row in `docs/testing/owed.md`, and the API plane page's trap list.

### Out of Scope

- **Any browser change.** No wording, contract or type changes. `NotFound` is already in the closed
  vocabulary and routes declare no per-route codes, so the generated contract does not move.
- **The Query workspace ignoring a failed status poll.** `TabExecutionPoller` reads only `data`, so
  any status failure leaves a tab in flight for five minutes with no message. That is pre-existing
  and user-visible, and it is tracked as a separate task. It matters more after this spec only in the
  fail-closed cases under *Consequences*.

  > **Closed by SPEC-233.** After one retry, a failed status poll now ends the tab's run, and the
  > banner gives the error code's wording (a 404 reads "That item no longer exists. Refresh and
  > try again."). Full entry: `docs/decisions/browser/`, *A failed status poll ends the Query
  > tab's run*.
- **`start()`, the Glue routes, and the results-conversion enqueue route.** That route's execution
  id travels in the body, and the plane proves it (SPEC-221).
- **A server-side shape check on the id.** Athena refuses a malformed one with the same
  `InvalidRequestException` as an unknown one (measured above), so after this spec it answers 404,
  like any id nobody owns.
- **SPEC-231's row-count route.** It calls the helper itself, and the guard covers it once it exists.
  SPEC-231's sentence that status and stop carry no check is marked superseded by whichever of the
  two specs merges second.
- **An execution-to-owner record.** None is needed, which is the point.
- **The results location under the IdC transition.** It is recorded below as a consequence, not
  built.

### Consequences, stated rather than mitigated

- **A workgroup that enforces its own result location makes every execution route answer 404** for
  every user's own queries, so the whole query surface stops, loudly. Today's workgroup does not
  enforce one; the transition may. Moving the proof is one edit in `cpcommon.results`, and it has to
  move with the location, just as results-conversion's already must.
- **An id held across a change of the results prefix is refused.** SPEC-220 moved the prefix once.
  No id reaches a route past a reload: the Explorer's cost ledger keeps ids in session storage,
  and none of them is ever polled.

---

## Functional Requirements

### FR-001: One ownership predicate, shared by the API and results-conversion

#### Description:

`owned_results_key(location: object, bucket: str, username: str) -> str | None`, in
`cpcommon/results.py`, returns the result object's key inside `bucket` (the part after
`s3://{bucket}/`) when `location` is a string starting with `user_results_prefix(bucket, username)`
and that key has no `.` or `..` segment (`cpcommon.paths.has_dot_segment`). Otherwise it returns
`None`. `rc_validate_authorize._owned_results_key` calls it, and raises its existing
`execution_not_found` refusal when it gets `None`.

#### Acceptance Criteria:

- [ ] For `alice` in bucket `b`, `s3://b/alice/system_settings/athenaresults/x.csv` returns
      `alice/system_settings/athenaresults/x.csv`.
- [ ] Each of these returns `None`: `None`; a value that is not a string; bob's prefix; the prefix
      cousin `alice2/…`; alice's path in another bucket; a location under alice's prefix carrying
      `../`; one carrying a `.` segment; and the pre-SPEC-220 prefix `s3://b/alice/athenaresults/x.csv`.
- [ ] results-conversion's own suite passes unchanged, including its dot-segment, prefix-cousin and
      unknown-equals-foreign cases, and `rc_validate_authorize.py` no longer makes its own
      `startswith` or `has_dot_segment` call. Its reason codes do not change. Its two operator
      messages for a refused location become one, which no test and no user sees.

### FR-002: status answers only for the caller's own execution

#### Description:

`status` reads the execution through `_owned_execution` and builds today's body from the document
that comes back. Both an execution Athena does not know (`InvalidRequestException`) and one whose
output is not the caller's raise `ApiError("NotFound", EXECUTION_NOT_FOUND_DETAIL)`.

#### Acceptance Criteria:

- [ ] The caller's own execution answers 200 with all six fields, as today (a FAILED one still
      carries `stateChangeReason` byte-identical), and the stub records exactly one call,
      `get_query_execution`.
- [ ] A foreign execution (bob's location) and an unknown id each answer 404 `NotFound`, and the two
      response bodies are **byte-identical** for the same request id. The foreign body carries none
      of the execution's fields.
- [ ] An execution with no recorded location, and one under the admin bucket's `fallback-results/`,
      get the same 404.
- [ ] An `AccessDeniedException` from the read still answers 403 `AccessDenied`, and a throttle or
      any other fault still rises to the outer classifier.
- [ ] The span carries `execution_id` on a refused request as well as on an answered one, and
      `execution_ownership` is `unknown` for the unknown id and `foreign` for the foreign one.
      Neither value appears in the response body.
- [ ] Every existing status, results and stop test, apart from the attribution test that now drives
      a refusal on purpose, asserts its own expected status code. A test that asserts only a call
      list, a header or an absence would otherwise stay green by testing the new 404.

### FR-003: stop proves ownership before it stops

#### Description:

`stop` calls `_owned_execution` first, and calls `StopQueryExecution` only for the caller's own
execution. Its existing mapping, where Athena's `InvalidRequestException` from the stop answers 200,
is unchanged.

#### Acceptance Criteria:

- [ ] For the caller's own execution, it answers 200 `{}`, and the calls are exactly
      `[get_query_execution, stop_query_execution]`, both with the path id.
- [ ] For the caller's own execution that has already finished (the stop raises
      `InvalidRequestException`), it answers 200 `{}`.
- [ ] A foreign execution and an unknown id each answer 404 `NotFound` with byte-identical bodies,
      and `stop_query_execution` is **never called**.
- [ ] An `AccessDeniedException` on either call answers 403.

### FR-004: results proves ownership before it reads

#### Description:

`results` validates the page size first, because that is about the request and discloses nothing
about the execution. It then calls `_owned_execution`. Everything after that is unchanged: the
over-fetch, the header drop, 409 for a query that has not finished, and 400 for a malformed one.

#### Acceptance Criteria:

- [ ] For the caller's own execution, the calls are exactly `[get_query_execution,
      get_query_results]`. The existing results tests pass with the caller's own execution in their
      stub. Those that read `MaxResults` or `NextToken` from `stub.calls[0]` now pick the
      `get_query_results` call by operation name, and the two that assert one call become list
      equality over the two.
- [ ] A foreign execution and an unknown id each answer 404 with byte-identical bodies, and
      `get_query_results` is never called.
- [ ] A foreign execution whose results read would raise "has not yet finished" answers 404, not 409.
- [ ] A page size outside its range answers 400 `InvalidRequest` and makes no Athena call.

### FR-005: A guard, derived from the contract, over every route that names an execution

#### Description:

A test enumerates the `contract.ROUTES` entries whose path template contains `{queryExecutionId}`.
It drives each one through `router.route` twice: once against a stub whose `get_query_execution`
returns a foreign execution, and once against an unknown id.

#### Acceptance Criteria:

- [ ] The enumerated set includes `athena.status`, `athena.results` and `athena.stop` by name. It is
      asserted as a superset, not an equal set, so a new route joins without anyone editing the
      guard. (A guard over an empty set passes, which is why the three are named.)
- [ ] For every enumerated route, the foreign answer is 404 `NotFound` carrying
      `EXECUTION_NOT_FOUND_DETAIL`, the stub's calls are exactly `[get_query_execution]`, and the
      unknown-id body is byte-identical to the foreign one.
- [ ] Every `contract.ROUTES` path under `/v1/queries/` that carries a placeholder spells it
      `{queryExecutionId}`. Otherwise a route naming it `{executionId}` would escape the enumeration
      with nothing turning red.
- [ ] Removing the `_owned_execution` call from any one of the three routes turns this guard red.
      That is planted and reverted during the build, and recorded in the PR.

### FR-006: The record stops saying the exposure is preserved

#### Description:

Every site that says the API adds no ownership check, or that closing the gap needs an
execution-to-owner record, is rewritten if it is code or a test, and marked superseded in place if it
is a spec or a delivery doc. The API plane page gains the trap.

#### Acceptance Criteria:

- [ ] None of these still states the exposure: `stop()`'s docstring, `TestStop`'s first test, the
      attribution test in `test_catalog_observability.py`, and the `stopQuery` row in
      `apps/portal/info/component-inventory/catalog-feature.md`. The attribution test asserts the
      404 that it now drives.
- [ ] Each of these carries a supersede marker naming SPEC-232, and none is deleted: SPEC-199's
      Out-of-Scope bullet, its Premise 5, FR-006's description and third criterion, its "Recorded as
      OWED" line, and the matching paragraph in its delivery doc.
- [ ] The exposure row in `docs/testing/owed.md` no longer says it is unowned. It names SPEC-232,
      and says the gap is closed in code and the row is retired once the live check runs.
- [ ] `lambdas/info/planes/api.md` carries a bullet saying three things: an execution id is a claim,
      every route that names one proves it first, and a workgroup that enforces its own result
      location refuses them all.
- [ ] `grep -rn -i -E "no ownership check|execution-to-owner|execution→owner" lambdas/ docs/ apps/portal/info/`,
      excluding this spec's own file, finds only lines that are supersede-marked, that record
      history, or that state the corrected premise (the output location IS the record).

---

## Interface Contract

```python
# lambdas/control-plane-common/cpcommon/results.py
def owned_results_key(location: object, bucket: str, username: str) -> str | None: ...

# lambdas/api/routes/athena.py
EXECUTION_NOT_FOUND_DETAIL = "no execution with this id belongs to the caller"

def _owned_execution(context: RequestContext, client: Any) -> dict[str, Any]:
    """One get_query_execution on the route's own client. Returns the QueryExecution document,
    which is never empty: an absent document has no location, so it is refused.
    Raises ApiError("NotFound", EXECUTION_NOT_FOUND_DETAIL) for InvalidRequestException and for a
    location owned_results_key refuses, stamping execution_ownership first; anything else
    re-raises for the classifier."""

# call sites
client = _client(context)
execution = _owned_execution(context, client)
```

No environment variable, IAM, infrastructure or browser change.

## File & Folder Structure

```
lambdas/control-plane-common/cpcommon/results.py          # + owned_results_key
lambdas/control-plane-common/test_results_cpcommon.py     # new: owned_results_key's cases
lambdas/results-conversion-validate-authorize/rc_validate_authorize.py   # delegates
lambdas/api/routes/athena.py                              # + _owned_execution; status, results, stop
lambdas/api/test_athena_routes.py                         # owned stubs; FR-002–FR-005
lambdas/api/test_catalog_observability.py                 # stubs and one docstring
lambdas/api/test_catalog_routes.py                        # StubAthenaFailure gains a location
lambdas/info/planes/api.md                                # the trap
apps/portal/info/component-inventory/catalog-feature.md   # the stopQuery row
docs/testing/owed.md                                      # the exposure row's owner
docs/specs/SPEC-199-*.md, docs/spec-delivery/SPEC-199-*.md # supersede markers
```

## Implementation Phases

### Phase 1: The predicate

- `owned_results_key`, its tests, and results-conversion moved onto it (FR-001).

### Phase 2: The helper and the three routes

- `EXECUTION_NOT_FOUND_DETAIL`, `_owned_execution`, and `status`, `stop` and `results` calling it
  (FR-002 to FR-004). Existing stubs are given an owned execution explicitly, not through a
  default, because a factory default that satisfies the proof hides the proof from every test that
  uses it.

### Phase 3: The guard

- The contract-derived guard, and the plant in each of the three routes (FR-005).

### Phase 4: The record

- Docstrings, SPEC-199's supersede markers, the inventory row, the `owed.md` row, and the API
  plane page (FR-006).
- The register entry in `docs/decisions/identity-and-access/`, and a clause in its Fences if the
  budget holds one. The code settles the decision and the live check does not, so the entry lands
  with the code, and the supersede markers point at it.

### Phase 5: After the deploy

- Live check as a signed-in user, once `scripts/watch_ci.py --branch main` reports the deploy:
  - First, an unknown UUID on status. It answers 500 today and 404 after the deploy, so it proves
    the new image is serving.
  - An unknown UUID, and an execution the operator account starts with its output outside every
    user's prefix, each answer 404 `NotFound` on all three routes, with bodies identical apart from
    the request id. This is the same staging that measured the exposure above. A second signed-in
    user's execution, the true cross-user case, becomes a row in `docs/testing/owed.md`.
  - A query run from the workspace still polls, pages and stops, and View DDL still opens.
- The completion ritual, including the exposure row in `owed.md` retired against the live check.
