# Spec: The Catalog Surface — Athena & Glue

**ID:** SPEC-199
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-197 (the transport contract — route ids, the success/error envelopes, the generated TS↔Python agreement, `lib/apiClient.ts`, `apiRetryPolicy`, and the frozen `ServiceResult<T>`), SPEC-196 (the user credential plane — `user_client(service, identity)`, the assumed portal role that Lake Formation grants attach to, its per-container session cache, the three failure conditions this spec's routes surface, and **its Phase 5 item 4 — the Lake Formation verification, re-homed here because it needs an Athena route that does not exist until this spec**), SPEC-195 (the verified ID token whose `cognito:username` claim replaces the `username` parameter on the wire), SPEC-192 (`lib/runtimeConfig.ts` — the key this spec **removes**), SPEC-032/033/034 (the workgroup, the per-user results prefix, and the `username`-tagged Glue/Athena isolation this spec must not touch), SPEC-077/078 (no active database; the client-side `;` split), SPEC-106 (`toUserMessage` is the only source of user-facing wording, and the Athena engine-message rules that depend on `stateChangeReason` reaching the browser), SPEC-176 (`features/catalog/` — the layer being ported), SPEC-178/180/181/182/185 (the cost ledger, `null` ≠ `''`, the failure banner, the SQL disclosure, and export's `outputLocation`), SPEC-127/137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

## Overview

Everything analytical in this product runs through six calls: `StartQueryExecution`,
`GetQueryExecution`, `GetQueryResults`, `StopQueryExecution`, `GetDatabase` and `GetTables`. The Query
workspace and the Data Explorer both ride on them, through the one layer `features/catalog/` owns.
This spec moves those six calls behind the API and leaves everything above the service boundary alone.

It is a small surface with a large blast radius, because three of the repo's most expensive lessons
live inside it: results read before an execution finishes reached users as *"Contact the
Administrator"* on an ordinary first load (2026-08-16); a SQL `NULL` collapsed to `''` destroyed a
distinction no consumer can rebuild (SPEC-180); and the disclosed SQL is trusted **because** it is the
same string `StartQueryExecution` received (SPEC-185, discharged live). A port that loses any of those
looks completely healthy.

It is also where the arc's central claim gets its first real proof. Lake Formation grants attach to a
**principal**, and after SPEC-196 that principal is the same portal role, assumed by the API instead of
vended to the browser. So "every Lake Formation grant keeps enforcing unchanged" stops being an
argument here and becomes an observation: a granted user's query returns rows against the deployed
API, and a non-granted one is refused — in two different shapes, which is the part a careless
implementation flattens.

## Scope

### In Scope

- **Six routes** — Athena start, status, results, stop; Glue get-database and list-tables — each with
  a declared credential plane and an explicit `idempotent` flag (FR-001).
- **Server-side derivation** of the results location, the workgroup and the caller's identity: three
  values leave the wire entirely (FR-002).
- **`stateChangeReason` travelling verbatim on a 200**, and why that is not the server phrasing a
  message (FR-003).
- **The results shape**: paging on an opaque token, `null` ≠ `''`, Athena's first-page header row, and
  the `+1` overfetch (FR-004).
- **Results read only at `SUCCEEDED`** — a distinct wire code, the message-not-name mapping rule, and
  the caller-side guard that is *kept* (FR-005).
- **Stop**, and an explicit statement of what it does and does not authorize (FR-006).
- **Every polling and pagination loop stays in the browser** (FR-007).
- **Glue reads with Lake Formation filtering unchanged**, including the two distinct denial shapes
  (FR-008).
- **The disclosed SQL byte-identical to the `QueryString` Athena received** (FR-009).
- **The `;` split and the cost ledger stay in the browser**, and the retry rule's consequence for
  `useExploration` (FR-010).
- **Observability**: one span per route, with SQL text and engine text kept out of every field
  (FR-011).
- **The ported services**, with a disposition for each existing assertion (FR-012).
- **What leaves the browser**: `lib/athenaClient.ts`, `lib/glueClient.ts`, two `@aws-sdk/*`
  dependencies, and one runtime-configuration key (FR-013).

### Out of Scope

Things a reader would reasonably assume travel with "the catalog moved behind the API":

- **Saved queries and Save results.** Both are S3 — `savedQueries.service.ts`, `useSaveResults`,
  `SaveResultsDialog` — and belong to **SPEC-198**, even though `useSaveResults` lives in
  `features/catalog/`. This spec supplies `outputLocation` on the status body and stops there.
- **The table-builder, refresh and share planes.** They are queues — **SPEC-200**. Nothing here
  enqueues anything.
- **Any hook, component or user-visible behaviour.** `useQueryExecution`, `useQueryResults`,
  `useResultRowCount`, `useSchema`, `useQuerySpaces`, `useExploration`, `QueryWorkspace`,
  `DataExplorerWorkspace` and every one of their tests are unchanged. FR-012 is what makes that
  checkable rather than hopeful, with **one declared exception** (FR-010 AC4).
- **An execution-ownership check.** Athena authorizes `GetQueryExecution` / `GetQueryResults` /
  `StopQueryExecution` by **workgroup**, and this deployment has one shared workgroup — so today a
  browser holding another user's execution id can read that execution. The port preserves that
  exactly: the API adds no ownership check and removes none. It is recorded as a **pre-existing
  exposure owed a spec** (Premise 5), not fixed here, because a real fix needs an execution→owner
  record that does not exist.
- **`glue:GetTableVersions` and `glue:GetTable`.** The browser calls neither today; the refresh
  plane's read-backs are Python and the verification role's are CLI. No route is added for a caller
  that does not exist.
- **Raising or lowering any cap.** `DEFAULT_MAX_ROWS` (100), `ROW_COUNT_PAGE_SIZE` (1000),
  `POLL_INTERVAL_MS` (1500), `MAX_POLL_DURATION_MS` (5 min), `STMT_MAX_POLLS` (90) keep their values.
- **`connect-src`.** The Athena and Glue hosts stop being fetched by the browser, but the derivation
  is SPEC-194's and its final state SPEC-202's. This spec changes no CSP.
- **Retiring `lib/credentialRetry.ts`.** S3 and SQS still use it. SPEC-202.

### What the browser does today, and which spec replaces it

| Today | Owner |
|---|---|
| `runQuery` → `StartQueryExecutionCommand`, with `username`, `WorkGroup` and `OutputLocation` chosen in the tab | **This spec**, FR-002 — one `POST`; all three derived server-side |
| `getQueryStatus` → `GetQueryExecutionCommand` | **This spec**, FR-003 |
| `getQueryResults` → `GetQueryResultsCommand`, incl. the `+1` overfetch, the 1000 clamp and the header-row drop | **This spec**, FR-004 — the Athena-shaped half moves to Python |
| `stopQuery` → `StopQueryExecutionCommand` | **This spec**, FR-006 |
| `getDatabase` / `listTables` → `GetDatabaseCommand` / `GetTablesCommand` (paginated in the tab) | **This spec**, FR-008 — one Glue call per request; the walk stays in the service |
| `runStatementToCompletion`, `getTableDdl`, `useQueryExecution`, `useResultRowCount` — four polling/paging loops | **Unchanged**, FR-007. They loop over API calls instead of SDK calls |
| `splitSqlStatements` (SPEC-078), `explorerKeys.execution(sql)` + the per-tab cost ledger (SPEC-178/181) | **Unchanged**, FR-010 — the API never parses SQL and never caches |
| `lib/athenaClient.ts`, `lib/glueClient.ts`, `@aws-sdk/client-athena`, `@aws-sdk/client-glue` | **Deleted**, FR-013 |
| `withCredentialRetry` around every catalog call | **Removed from these two services**, FR-013 — SPEC-196 FR-006 does the re-assume server-side |
| `athenaWorkgroup` in the SPA's runtime configuration | **Removed**, FR-013 — the API Lambda's `ATHENA_WORKGROUP` |
| Every other AWS call in the browser | SPEC-198, SPEC-200 |

### Premises later specs must honour

1. **A loop that is in the browser today stays in the browser.** The API makes exactly one Athena or
   Glue call per request — counted on the route's own service client, never on botocore as a whole,
   since SPEC-196's per-container session cache makes an `sts:AssumeRole` fire on some invocations and
   not others (FR-001 AC6) — and it never waits, sleeps or retries on the user's behalf. SPEC-198's free-name route is
   the arc's **one** deliberate exception, and its justification (999 sequential probes for one
   gesture) does not generalise to a 1.5-second poll.
2. **The SQL string is opaque to the API.** It is not parsed, split, normalised, trimmed, lower-cased,
   validated or logged. Anything that needs to understand SQL lives in the browser or in a control
   plane.
3. **`stateChangeReason` is data about a query, not a message about a request.** It rides a 200 body
   and is mapped to authored wording by `lib/errorMessages.ts`. No later spec may move that mapping
   server-side; that would be SPEC-106 reversed by a route that looked like it was being helpful.
4. **Every catalog route is on the user plane.** There is no catalog call the API makes on its own
   behalf, and a route that reached for `api_client` would be issuing Athena or Glue calls with the
   execution role's identity — the exact fail-open SPEC-196 FR-005 exists to stop.
5. **Execution-id ownership is owed.** Any later spec that adds an execution→owner record should close
   the Out-of-Scope exposure above; until then `logs/service=api/` carrying `actor` on every catalog
   span is the only attribution that exists.

**AMENDED 2026-08-18 — FR-002's server-side derivation has a known successor, and the results
location is the part that moves.** Moving the workgroup, the results location and the caller's
identity off the wire is right and is not in question. What changes in the target environment
(`transition_plan.md` §3.5, §3.9) is what the derivation *derives*:

- **The workgroup becomes an IAM Identity Center enabled workgroup**, whose **user-identity-based S3
  prefix** feature appends **`${user_id}`** to the results path — substituted by Athena when it
  writes results — and requires *Override client-side settings*. So
  `s3://{bucket}/{username}/athenaresults/`, which this spec derives from the verified username, may
  stop being the path results land at. *Whether the feature can be turned off is an open Phase 0
  question (`transition_plan.md` §3.5), so treat this as likely rather than certain. Note also that
  Athena's `${user_id}` and the `${identitystore:UserId}` **IAM policy variable** used in the Access
  Grants location role's policy are two different mechanisms — do not merge them.* Anything reading a result
  object back from the path it *requested* breaks there; this spec's own FR-004 reads results through
  `GetQueryResults` and is safe, but the export path (SPEC-185's `outputLocation`) and the
  save-results copy are the surfaces to re-check. Keep the derivation in **one function** for exactly
  this reason — it is one edit there and a hunt otherwise.
- **A workgroup's authentication method is fixed at creation** and an existing workgroup cannot be
  converted, so the target's workgroup is a new resource rather than a modified one. Nothing here
  needs to anticipate it beyond not hard-coding the current workgroup's name outside configuration.
- **Three quotas arrive with that workgroup and are worth knowing now**: queries time out at 30
  minutes by default and **one hour maximum, not raisable**; entitlement changes take up to an hour
  to take effect; and an IdC-enabled workgroup cannot be modified to support resource-level IAM
  permissions or identity-based IAM policies. None of them change a requirement below.
- **What does not move is this spec's central claim.** Lake Formation grants attach to a principal,
  and FR-008's two distinct denial shapes are properties of Lake Formation rather than of which
  principal reached it. When the principal becomes an Identity Center identity instead of the assumed
  portal role, the shapes are the same and the tests still mean what they meant.

---

## Functional Requirements

### FR-001: The route set, the planes and the retry declarations

#### Description:

Six routes, named once in `apicommon/contract.py`, generated into TypeScript, dispatched from the
table. No route waits on a query, so SPEC-193's 29-second integration ceiling is not approached by
anything in this surface.

#### Acceptance Criteria:

- [ ] Exactly six routes are added, with these ids, methods, paths, planes and `idempotent` flags:
      `athena.start` (`POST /v1/queries`, user, **false**), `athena.status`
      (`GET /v1/queries/{queryExecutionId}`, user, true), `athena.results`
      (`GET /v1/queries/{queryExecutionId}/results`, user, true), `athena.stop`
      (`POST /v1/queries/{queryExecutionId}/stop`, user, **true**), `catalog.database.get`
      (`GET /v1/catalog/databases/{database}`, user, true), `catalog.tables.list`
      (`GET /v1/catalog/databases/{database}/tables`, user, true).
- [ ] `athena.start` is the only non-idempotent route, and `athena.stop` is idempotent **despite being
      a `POST`** — the execution id is in the path, so a repeat cannot stop a different query and a
      second stop on a terminal execution changes nothing. A test reads the flags off the generated
      table; deriving either from the HTTP method is what SPEC-197 FR-008 forbids and both rows here
      would get it wrong.
- [ ] `apiRetryPolicy('athena.start')` is `false`. A test drives a failing start through
      `useExploration` and asserts **exactly one** `apiRequest` — the incident this rule exists for is
      the two `StartQueryExecution` calls 1.1 s apart that CLAUDE.md records as `retry: 1`.
- [ ] Every one of the six appears in `ROUTE_PLANES` as `user`, asserted by a test that reads the
      generated table rather than a hand-written list, so a seventh route added later cannot be
      omitted (SPEC-197 FR-006).
- [ ] No route in this spec calls `api_client`. A test asserts `lambdas/api/routes/athena.py` and
      `catalog.py` reach `boto3` only through `user_client` — which SPEC-196's AST sweep already
      enforces repo-wide, and is re-asserted here because these are the first routes with a real
      isolation obligation.
- [ ] **No route makes more than one AWS call — counted on the ATHENA or GLUE client the route holds,
      never on botocore as a whole.** The count must name its client because `sts:AssumeRole` may or may
      not fire on any given invocation: SPEC-196 caches the assumed session per container, so a cold
      invocation issues an STS call the next one does not, and "one botocore call per request" is
      unsatisfiable on the first request and satisfiable on the second. A test asserts **exactly one**
      call on the client returned by `user_client('athena', …)` / `user_client('glue', …)` for each of
      the six routes, and says nothing about STS. The distinguishing case is `catalog.tables.list`: a
      server-side `NextToken` walk would satisfy every behavioural test in this spec and quietly make the
      API a loop over a user-controlled collection.

### FR-002: Start — the wire carries no identity, no bucket and no workgroup

#### Description:

`runQuery` today takes `username`, reads `VITE_ATHENA_WORKGROUP` in the tab, and builds
`s3://{userSpaceBucket()}/{username}/athenaresults/` in the browser. All three become server-side
derivations from the verified token and the API's own environment.

#### Acceptance Criteria:

- [ ] The request body is exactly `{sql: string, database?: string}` and nothing else. A body carrying
      `username`, `outputLocation`, `workGroup` or any unknown key is refused **400 `InvalidRequest`**
      by SPEC-197's validator — not ignored. Ignoring an unknown key is how a field comes back.
- [ ] `OutputLocation` is `s3://{USER_SPACE_BUCKET}/{username}/athenaresults/`, where `username` is
      the verified claim (SPEC-196's `UserIdentity`) and the bucket is the API's environment. A test
      supplies a request whose body and query string both say `mallory` while the verified claim says
      `alice`, and asserts the `StartQueryExecution` call carries `alice`'s prefix. **The fixture must
      disagree** — one where the body and the claim agree passes over the defect.
- [ ] `WorkGroup` comes from the API Lambda's required `ATHENA_WORKGROUP` variable, which raises at
      first read when unset rather than defaulting (SPEC-196's convention). A defaulted workgroup sends
      queries to Athena's `primary`, whose results location is the account default — a silent write
      outside the isolation model.
- [ ] `database` is optional and, when absent, `QueryExecutionContext` is **omitted entirely** rather
      than sent empty — SPEC-077's rule, moved not re-decided. A test asserts the key is absent from
      the botocore call for the three call sites that send no database — `useTabRuns`' two `runQuery`
      calls and `useExploration`'s — and present for the **two** that do. Both reach it through
      `runStatementToCompletion`, which takes `database` as a **required** parameter and forwards it:
      `getTableDdl`'s `SHOW CREATE TABLE`/`SHOW CREATE VIEW`, and **`useRunDdl`**, which runs a user's
      own DDL against a chosen database. Naming only `getTableDdl` leaves the fixture set one caller
      short on the exact key this criterion is about.
- [ ] The response is `{queryExecutionId: string}`. Athena accepting the call without returning an id
      is **500 `InternalError`** at the API, replacing today's client-minted `AthenaNoExecutionId`.
      **The conclusion is right and the reason in `athena.service.ts`'s comment is not:** that comment
      claims the code exists "so the mapper decides that, not a fallthrough", but `lib/errorMessages.ts`
      carries **no rule of any kind** for `AthenaNoExecutionId` — no `code` rule and no `MATCH_RULE` —
      so it reaches the generic sentence *by* fallthrough today, which is exactly what it says it
      avoids. Nothing user-visible moves, because `InternalError` falls through to the same sentence; a
      test asserts the two render byte-identically, and the stale comment goes with the code.
- [ ] `sql` is passed to `QueryString` **unmodified** — see FR-009.
- [ ] The route performs no SQL inspection of any kind (Premise 2), asserted by a sweep over
      `lambdas/api/` for `split`, `;`-scanning, `strip()` on the statement, and any SQL keyword
      literal.

### FR-003: Status — `stateChangeReason` travels verbatim, on a 200

#### Description:

A query Athena refuses is not an error anywhere in the plumbing: `GetQueryExecution` succeeds and the
reason arrives as a field. `lib/errorMessages.ts` holds six ordered `MATCH_RULES` that read that raw
engine text and choose authored wording — unqualified table, table not found, column not found,
Lake Formation permission, still-running, syntax error. If the API swallows or replaces the field,
every one of those becomes unreachable and every failed query says *"Something went wrong. Contact the
Administrator."* Nothing looks broken.

#### Acceptance Criteria:

- [ ] The 200 body is `{queryExecutionId, state, stateChangeReason: string | null, dataScannedBytes:
      int | null, engineExecutionTimeMillis: int | null, outputLocation: string | null}`, and `state`
      is a `Literal` over the **five** states this app models — `QUEUED`, `RUNNING`, `SUCCEEDED`,
      `FAILED`, `CANCELLED` — matching `catalog.types.ts`'s `QueryState` and this spec's own Data Model
      exactly. (Athena's API documents a sixth, `CANCELLING`; the browser has never modelled it and this
      port does not add it, because a state the client's `isTerminalState` and switch arms do not know
      would arrive as an unhandled value on the one path SPEC-181 reads. Widening the union is a
      behaviour change and belongs to whichever spec wants the behaviour.) A missing `Status.State`
      defaults to `QUEUED`, as today.
- [ ] `stateChangeReason` is Athena's string **byte-identical**, never truncated, never mapped to a
      code, never merged into `detail`. A test round-trips
      `Insufficient Lake Formation permission(s): Required SELECT on table x` and
      `SYNTAX_ERROR: line 1:8: Column 'foo' cannot be resolved` through the route and then through
      `toUserMessage`, asserting the two authored sentences the existing `MATCH_RULES` produce. **The
      assertion is on the mapped sentence, not on the field being present** — a field that arrives
      truncated at 100 characters is present and still breaks two of the six rules.
- [ ] A FAILED or CANCELLED execution is a **200**, never a 4xx/5xx envelope. A test asserts the
      status code for a FAILED execution is 200 and that `ServiceResult.success` is `true`. Mapping a
      failed query to an error envelope is the change that looks most correct and destroys the
      `stateChangeReason` path, the `FAILED`/`CANCELLED` codes `useExploration` mints, and SPEC-181's
      last-good-rows fallback in one move.
- [ ] `outputLocation` is present exactly when Athena reports it, because SPEC-185's export copies
      that object and SPEC-198's Save results parses it. A test asserts it survives for a SUCCEEDED
      execution.
- [ ] `dataScannedBytes` and `engineExecutionTimeMillis` are absent (`null`) on a non-terminal
      execution, as Athena reports them. SPEC-181 depends on this: a poll that reports a confident
      `0` freezes the tab's cost figure at zero. A test asserts a QUEUED status body carries `null`
      for both, not `0`.
- [ ] The route is the only place the browser learns a query's state. No route infers it, caches it,
      or answers from a previous poll.

### FR-004: Results — paging, `null` ≠ `''`, and Athena's header row

#### Description:

The whole of `getQueryResults`'s Athena-shaped logic — the `+1` first-page overfetch, the 1000 clamp,
the header-row drop and the NULL preservation — moves to Python. The browser sends a page size and a
token and gets clean columns and rows.

#### Acceptance Criteria:

- [ ] `GET /v1/queries/{id}/results?nextToken=&maxRows=` returns
      `{columns: [{name, type}], rows: list[list[str | None]], nextToken: string | null}`. This is
      conformant with SPEC-197 FR-002 rather than an exception to it: **`nextToken` is the paged
      contract and `items` is not** — a page that is a bare homogeneous collection names it `items`
      (SPEC-198's `GET /v1/objects`), and a page that is not carries its own payload keys beside
      `nextToken`, which a tabular page is, because wrapping two parallel shapes as `items` would either
      lose the column list or nest the rows a level deeper for every consumer.
- [ ] **`null` is SQL NULL and `""` is the empty string, and they are distinct on the wire.** A
      fixture whose result set has, in one row, an absent `VarCharValue` beside a present empty one
      must serialise as `[null, ""]` — asserted **on the raw response body text**, not on a parsed
      structure. The wrong implementation is `d.get("VarCharValue", "")` or `... or ""`, which is
      indistinguishable from the right one for every non-null cell and for every fixture that has no
      NULLs, and it destroys what SPEC-180's Value panel, SPEC-181's `isNull` and SPEC-185's copy all
      read.
- [ ] The generated TypeScript type is `(string | null)[][]`. This is the contract's first
      **nested** list and its first `list[X | None]`; SPEC-197 FR-005's closed vocabulary must accept
      both by recursion, and a test feeds this exact annotation to the generator and asserts the
      emitted type. If the walker handles one level only, the failure is at generation time, which is
      the right place for it.
- [ ] `nextToken` is opaque per SPEC-197 FR-002: stored and returned unmodified, URL-encoded by the
      client. A test round-trips an Athena-shaped token containing `+`, `/` and `=` and asserts the
      value botocore receives is byte-identical to the value emitted. Unencoded, `+` decodes to a
      space and the next page silently restarts from the beginning.
- [ ] `MaxResults` is `min(maxRows + 1 if first page else maxRows, 1000)` — the existing arithmetic,
      moved. A test asserts that at `maxRows = 1000` the first page requests 1000 and therefore nets
      **999** data rows; `useQueryResults` numbers rows from actual page lengths and must keep being
      allowed to see non-uniform pages.
- [ ] Athena repeats the column names as the first row of the **first** page of a `SELECT` only. That
      row is dropped when — and only when — `nextToken` was absent and the row matches the column
      metadata element-for-element. A test asserts it is **not** dropped on a continuation page, and
      that a first page whose first genuine data row happens to equal the header **is** dropped —
      today's accepted foot-gun, preserved rather than quietly fixed.
- [ ] `columns[].type` is Athena's raw type string; `normalizeColumnType` stays client-side in
      `catalog.format.ts`, unchanged. A DDL/CTAS statement that produced no result set returns empty
      columns and rows with a 200 — not a 404, not an error.
- [ ] `maxRows` is validated as an integer in `[1, 1000]`; anything else is 400 `InvalidRequest`. The
      browser never sends an out-of-range value, which is exactly why the check must exist here.

### FR-005: Results are read only at `SUCCEEDED` — a wire code, and a guard that stays

#### Description:

`GetQueryResults` against a QUEUED execution is a **400 `INVALID_QUERY_EXECUTION_STATE` — "Query has
not yet finished"**, whose exception name (`InvalidRequestException`) mapped to nothing and reached
users as the generic *"Contact the Administrator"* on an ordinary first load of the Data Explorer
(settled 2026-08-16). The API now sits in that path. It maps the state to its own code — and the
caller-side guard is **kept**, not replaced.

#### Acceptance Criteria:

- [ ] A new error code **`QueryNotFinished` → HTTP 409** is added to SPEC-197's enum (additive within
      `/v1/`, Premise 3 there) and to `lib/errorMessages.ts` with the sentence *"The query is still
      running. Give it a moment and try again."* — **byte-identical** to today's, asserted by a test,
      so no user-visible wording moves.
- [ ] The mapping is on the **message**, never the exception name. `InvalidRequestException` is also
      what Athena raises for a MALFORMED_QUERY at submit; a test asserts a malformed-query
      `InvalidRequestException` maps to **400 `InvalidRequest`** while a
      `INVALID_QUERY_EXECUTION_STATE` one maps to **409 `QueryNotFinished`**. A mapper keyed on the
      name passes any test that exercises one of the two at a time — which is precisely how the
      original defect survived.
- [ ] `errorMessages.ts`'s existing `MATCH_RULE` for `invalid_query_execution_state|query has not yet
      finished` is **replaced by a `code` rule** on `QueryNotFinished`, and the match rule is deleted.
      The reason it could not be a code rule before was that `InvalidRequestException` was ambiguous;
      the API resolves that ambiguity at the one layer holding the message, so the client rule can now
      key on the code — which is stronger, because a `code` rule outranks every message rule.
- [ ] **`ExplorationResultsRegion`'s `state === 'SUCCEEDED'` gate is unchanged and its test asserts on
      the CALL, not the screen.** With the 409 mapping in place, removing the gate produces a *correct-
      looking* "still running" message instead of the old generic one — so a screen assertion cannot
      fail any more. The test asserts `useQueryResults` issues **zero** `apiRequest` for route
      `athena.results` while `state` is `QUEUED` or `RUNNING`.
- [ ] The trap is restated in the test's name and comment: **`isPending` is not a substitute.**
      Between `StartQueryExecution` resolving and the first poll landing, `state` is `null` and
      `isPending`'s `state !== null && !isTerminalState(state)` clause is already false. A test drives
      exactly that window.
- [ ] `useResultRowCount`'s background walk is gated too, but **by a different mechanism, and the spec
      must not describe one the code does not have.** It reads no state: `QueryWorkspace` passes it
      `hasResultSet ? displayExecutionId : null`, where `hasResultSet` is
      `displayExecutionId !== null && results.columns.length > 0` — a gate on *columns having arrived*,
      which is a consequence of a succeeded execution rather than a reading of its state, and the hook's
      own `enabled: queryExecutionId !== null` is what stops the walk. That is preserved unchanged. The
      assertion is on the property, not the mechanism: a test drives a QUEUED and a RUNNING execution and
      asserts **zero** `athena.results` requests attributable to `useResultRowCount`. Restating it as
      "the same gate" would license a builder to replace the columns check with a state check, which is a
      behaviour change in a spec whose whole claim is that no hook is edited.

### FR-006: Stop, and what it does not authorize

#### Description:

`POST /v1/queries/{id}/stop`. One call, no body, no ownership check — because there is none today and
inventing one here would need a record that does not exist.

#### Acceptance Criteria:

- [ ] The route takes no body. A 200 returns `{}` (SPEC-197 FR-001's no-204 rule), and the browser's
      `stopQuery` keeps returning `ServiceResult<void>`.
- [ ] Stopping an already-terminal execution is a success from the caller's point of view: Athena's
      refusal for a terminal execution maps to 200, not an error, because the poller observes
      `CANCELLED`/the terminal state either way and today's `stopQuery` failure is swallowed at the
      call site. A test asserts the mapped result for a terminal-execution stop.
- [ ] The API adds **no** ownership check and **removes** none. A test asserts the route passes only
      the path's `queryExecutionId` to botocore and consults nothing else. The Out-of-Scope entry and
      Premise 5 are the record that this is a known, preserved property rather than an oversight — a
      port that silently added a check would break `getTableDdl`, which stops nothing, and a port that
      silently removed one would be widening; there is nothing to remove.
- [ ] The span stamps `actor` and `execution_id` (FR-011), so a cross-user read is at least
      attributable in `logs/`. That is the entire mitigation this spec ships, and saying so is the
      point.

### FR-007: Every polling and pagination loop stays in the browser

#### Description:

"The API waits for the query" is the shape a reader reaches for, and it is wrong twice over: it would
put a multi-minute wait behind a 29-second integration ceiling that **is not raisable on an HTTP API**,
and it would make one route hold a Lambda open for the duration of a user's query.

#### Acceptance Criteria:

- [ ] Four loops stay exactly where they are: `useQueryExecution` (TanStack `refetchInterval`,
      `POLL_INTERVAL_MS` 1500, `MAX_POLL_DURATION_MS` 5 min), `runStatementToCompletion`
      (`STMT_POLL_INTERVAL_MS` 400 × `STMT_MAX_POLLS` 90), `useQueryResults`' `NextToken` paging, and
      `useResultRowCount`'s background walk. All four are **unchanged apart from what they call**, and
      their test files are unchanged byte for byte.
- [ ] A sweep over `lambdas/api/` asserts no module sleeps, waits, polls or loops on an AWS response:
      no `time.sleep`, no botocore waiter, no `while` over a `NextToken`. Verified by committing a
      deliberate violation and confirming red (SPEC-176's rule — a guard read from the config file
      proves nothing).
- [ ] **The ceiling is computed, not asserted.** A test names the schedulable unit — one AWS API call
      per request — and shows the slowest route in this surface is `athena.results` at
      `ROW_COUNT_PAGE_SIZE` (1000 rows), sub-second, against the 29-second budget. It also states what
      the bound would be under the rejected design: a 5-minute query is 10× the ceiling, so
      "the API waits" does not fail at the margin, it fails always.
- [ ] The consequence of moving the loops behind a gateway is stated and accepted: a 5-minute query
      is ~200 `athena.status` requests, and `useResultRowCount` over a million rows is ~1000
      `athena.results` requests — the same counts as today, one extra hop each. Both now meet API
      Gateway account throttling, `apiRequest` **never retries a 429** (SPEC-197 FR-008), and the walk
      already swallows a failed page into `total: null` and falls back to the loaded-count form. A test
      asserts a 429 mid-walk leaves `total` null and raises no banner. No new mechanism is added.

### FR-008: Glue reads, and the two shapes a Lake Formation denial takes

#### Description:

`GetDatabase` and `GetTables`, unchanged in meaning. This is where "every Lake Formation grant keeps
enforcing unchanged" is asserted, because LF attaches to the **principal** — the same portal role,
now assumed by the API (SPEC-196) instead of vended to the browser.

**This spec inherits SPEC-196 Phase 5 item 4, which that spec recorded as owed and re-homed here.**
Lake Formation is not modelled by the IAM policy simulator at all, so nothing SPEC-196 could run
settled whether LF still authorizes the assumed-role session; confirming it needs **one Athena query on
the user plane against the caller's own database, returning rows**, and no such route existed until this
spec. That query is Phase 5's first item and it discharges SPEC-196's item 4 as well as FR-008 AC7 here.
Running it from a laptop proves nothing about this layer — the local CLI identity is an IAM **user**,
a different principal, and LF filters its catalog to empty (SPEC-186 FR-004's own finding).

#### Acceptance Criteria:

- [ ] `GET /v1/catalog/databases/{database}` returns `{name: string}`. Glue's
      `EntityNotFoundException` maps to **404 `NotFound`**. The browser's `getDatabase` keeps returning
      `{code: 'NotFound'}`; a test confirms the user-visible sentence is unchanged — today's authored
      *"Database "x" does not exist yet."* is already discarded by `toUserMessage`'s non-passthrough
      `NotFound` code rule, so nothing is lost, which is checked rather than assumed.
- [ ] `GET /v1/catalog/databases/{database}/tables` returns `{items: GlueTableSummary[], nextToken:
      string | null}` — **one `GetTables` call per request** (FR-001). `listTables` keeps its exact
      signature `Promise<ServiceResult<GlueTableSummary[]>>` and loops `apiRequest` internally, so
      `useSchema`, `useAllSchemas` and `fetchSchema` are untouched.
- [ ] `EntityNotFoundException` on the tables route returns **200 with an empty `items`**, not a 404 —
      SPEC-176's forgiving semantics moved, not re-decided: a not-yet-created database is an empty
      schema browser, never an error banner. A test asserts the 200 and carries the reasoning in its
      name.
- [ ] **Lake Formation denies in two different shapes and the port must preserve both.** (a) A Glue
      read the caller has no `DESCRIBE` on raises `AccessDeniedException` naming *"Insufficient Lake
      Formation permission(s)"* → **403 `AccessDenied`**, envelope-shaped, `detail` carrying no AWS
      text (SPEC-197 FR-003). (b) An **Athena query** the caller has no `SELECT` on does not fail the
      call at all — the execution reaches `FAILED` and the reason names Lake Formation, arriving on a
      **200** status body (FR-003). A test asserts both, in the same file, because an implementation
      that maps every LF denial to 403 passes (a) and silently converts (b) into an error envelope,
      losing the authored *"You don't have permission to run that query."* sentence.
- [ ] A 403 from either route is **never** a re-login (SPEC-197 FR-003, SPEC-196 FR-007). A test
      asserts an `AccessDenied` failure invokes no `setUnauthenticatedHandler` callback. Collapsing 401
      and 403 makes the isolation model present as a broken session.
- [ ] **No IAM change** — the assumed portal role already holds every permission these six calls need,
      and this spec adds no statement to `portal-role-analytics`, `portal-role-permissions` or
      `portal-role-shared-space`. **The guard is a named-absence assertion, not a golden diff**
      (SPEC-196 FR-008's corrected technique): a test that snapshots the rendered templates during the
      build and diffs them against themselves compares a copy of the answer with itself and passes
      whatever happens. Two assertions that can fail: (a) each of the three templates is byte-identical
      to its **pre-change git blob** at this spec's base commit, read with `git show`; and (b) the
      rendered policies name **no** new `Resource` and **no** `athena:` or `glue:` action absent from
      the base. (a) catches a tidy, (b) catches a widening a re-baselined snapshot would absorb.
- [ ] **The LF positive is a Verification item and it discharges an inherited obligation.** A real
      `SELECT` run through `athena.start` against the caller's own database reaches `SUCCEEDED` and
      returns rows — the observation the arc's central claim rests on, and the discharge of SPEC-196
      Phase 5 item 4. It is recorded against **both** specs by date, in
      `docs/testing/arc-b-api-container-e2e.md`, and SPEC-196's delivery doc gains a pointer to it. An offline
      test cannot stand in: every one of them supplies its own botocore fixture and can only prove what
      it was told.
- [ ] **The route adds no membership or existence check of its own.** It passes the path's database
      name to Glue and maps what comes back. Whether a foreign database and an absent one are
      indistinguishable is Lake Formation's property, not this API's, and it is a **Verification item**
      (Phase 5) rather than an offline assertion — because the offline suite supplies its own botocore
      fixtures and can only prove what it was told.

### FR-009: The disclosed SQL is byte-identical to the `QueryString` Athena received

#### Description:

The Data Explorer writes SQL the user did not, and that SQL is an invoice. SPEC-182 FR-005's
disclosure is trusted **because** `useExploration` renders once, runs that string, and shows the same
value; SPEC-185 discharged the byte-identity live against Athena's own `QueryString`. A JSON hop now
sits in the middle.

#### Acceptance Criteria:

- [ ] The start route passes `sql` to `QueryString` with **no** transformation: no `strip()`, no
      newline normalisation, no trailing-semicolon handling, no unicode normalisation, no re-encoding.
      A test asserts byte-identity for a statement containing a trailing newline, a leading blank
      line, `'O''Brien'` (SPEC-178's doubled-quote escape), a `--` comment, an embedded `;` inside a
      literal, a tab, and a non-ASCII character.
- [ ] `apiRequest`'s JSON body and the API's JSON parse are asserted to round-trip the same string —
      the assertion is a **comparison of the two byte strings**, not "the query ran". A statement
      mangled by a `strip()` still runs, still returns rows, and still looks right in the disclosure;
      only the comparison catches it.
- [ ] `GeneratedSqlDisclosure`, `renderExplorationSql`, `useExploration` and their tests are unchanged.
      The disclosure keeps reading `useExploration.sql` and never re-renders (SPEC-182's rule).
- [ ] Live (Phase 5): open the disclosure, copy the statement, and compare it to the `QueryString` on
      a `GetQueryExecution` read-back of that execution id — the same way SPEC-185 discharged it. A
      Chromium pass corroborates; the comparison itself is browser-independent.

### FR-010: The `;` split, the cost ledger, and the one behaviour that changes

#### Description:

Two client-side mechanisms that a port would be tempted to move, and one that genuinely changes.

#### Acceptance Criteria:

- [ ] `splitSqlStatements` stays in `features/query/query.sql`, unchanged, with `queryPure.test.ts`
      unchanged byte for byte. The API accepts **one** statement per start call and does not detect or
      refuse a multi-statement string — Athena already rejects those, and a server-side detector would
      be the second SQL lexer SPEC-183 forbids. A sweep asserts no SQL splitting in `lambdas/api/`.
- [ ] The cost ledger is untouched: `explorerKeys.execution(sql)` with `staleTime: Infinity` **and**
      `gcTime: Infinity`, the per-tab `scannedByExecution` map keyed by execution id, and
      `DataExplorerWorkspace`'s read-during-render before `recordScan`. `useExplorationTabs.test.ts`
      and `useExploration.test.ts` are unchanged. A test asserts a repeated identical exploration
      issues **zero** `athena.start` calls — the cache-hit property, now counted at the transport.
- [ ] The API caches **nothing**. No results cache, no execution-status cache, no `Cache-Control`
      other than SPEC-197's `no-store`. A cached status would make the poll lie about a terminal state
      and a cached result page would be a cross-user disclosure whose first reader sees exactly the
      right answer.
- [ ] **One shipped behaviour changes, deliberately.** `useExploration`'s start query inherits
      TanStack's default `retry: 1` today, which is why a failing apply issues two
      `StartQueryExecution` calls ~1.1 s apart. Under FR-001 it becomes `apiRetryPolicy('athena.start')`
      = `false`: one call, one failure, surfaced immediately. Nothing user-visible moves (the banner is
      the same), a transient start failure is no longer masked, and **CLAUDE.md's Data Explorer note
      telling a live-checker to "count executions on a statement that SUCCEEDS" becomes stale** — the
      completion ritual corrects it rather than leaving a live-check instruction that describes
      behaviour the app no longer has.

### FR-011: Observability — and the two fields that must never be logged

#### Description:

One span per route through `cpcommon.observability` into `logs/service=api/`, with `env` and `version`
populated (SPEC-186 FR-005). The field rule — *user metadata in, file contents out* — binds unusually
hard here, because **two** of this surface's values routinely carry a user's own data.

#### Acceptance Criteria:

- [ ] Each catalog request stamps `route_id`, `actor`, `execution_id` (where the route has one),
      `database` (where it has one), `state` (status route), `row_count` and `column_count` (results
      route), `duration_ms` and, on failure, `code`.
- [ ] **The SQL statement is never a field value.** SPEC-178 interpolates user values into SQL through
      `sqlLiteral`, so a `WHERE name = 'O''Brien'` statement *is* file contents. The span carries
      `sql_bytes` (the length) and nothing else about the statement. A test starts a query whose SQL
      contains a distinctive literal and asserts the string appears in **no** emitted record — the
      obvious wrong implementation is a helper that stamps the request body, and it would look like
      good telemetry.
- [ ] **`stateChangeReason` is never a field value.** Athena quotes the offending value back
      (`Cannot cast VARCHAR 'O''Brien' to INTEGER`), so the reason is file contents by the same
      argument. The span carries `state` alone. A test asserts a distinctive cell value in a
      `stateChangeReason` fixture appears in no record.
- [ ] **Result rows and column names are never field values.** `row_count` and `column_count`, on
      SPEC-197's `username_count` precedent.
- [ ] SPEC-195's `error.stack` treatment is inherited explicitly, not assumed, and it is **credentials
      only** — a test raises inside each route with a `__cause__` carrying a **token-shaped** sentinel
      and asserts it reaches no byte of any record, `error.stack` included. It asserts **nothing** about
      user-data-shaped strings in a stack: the 2026-07-23 decision **accepts** file contents reaching
      `error.stack` (`logs/` is admin-only, the absolute rule binds the values a call site *chooses* to
      emit, and a stack is diagnostic metadata) and pins that acceptance with
      `test_ACCEPTED_the_span_error_stack_may_carry_file_contents`, whose failure is meant to trigger
      revisiting the decision rather than deleting the test. Requiring a user-data scrub here would put
      this spec in direct conflict with that tripwire and reopen a settled fork. The three criteria
      above bind **fields**, which is where the rule actually applies, and they are unaffected.
- [ ] No record carries an email address, on any path.

### FR-012: The ported services, with every existing assertion accounted for

#### Description:

`athena.service.ts` and `glue.service.ts` keep their names, their exported signatures and their
docstrings' promises; their innards go from `withCredentialRetry(getAthenaClient, …)` to `apiRequest`.
The measure of a good port is that no assertion is quietly lost, so each existing assertion is *kept*,
*moved to Python with its reasoning carried over*, or *kept on both sides* — written down, because
"we moved the tests" is the claim nobody can check a year later.

| Existing assertion (`catalogServices.test.ts`) | Disposition |
|---|---|
| `runQuery` sends the workgroup from the environment | **moved** to Python (`ATHENA_WORKGROUP`) |
| `runQuery` omits `QueryExecutionContext` with no database, sends it with one | **moved** |
| `runQuery` targets `{username}/athenaresults/` | **moved**, and strengthened: the fixture's body disagrees with the claim (FR-002) |
| `runQuery` honors an explicit `outputLocation` (SPEC-055 shared routing) | **DELETED, and it is the one deletion in this table** — the parameter goes (AC2 below), so the assertion has no subject. Named here rather than left out, because "no assertion is deleted" was the claim and one is |
| a missing `QueryExecutionId` is a failure | **moved** (500 `InternalError`); **kept** on the client as "a 500 envelope is `{success: false}`" |
| `getQueryStatus` maps state, reason, statistics and output location | **both** — Python maps the botocore shape, TS maps the wire shape to `QueryStatus` |
| a missing `Status.State` defaults to `QUEUED` | **moved** |
| `getQueryResults` drops the first-page header row and not a continuation's | **moved** |
| the `+1` overfetch and the 1000 clamp | **moved** |
| an absent `VarCharValue` is `null`, a present empty one is `''` | **both** — Python on the serialised body, TS on the parsed page (FR-004) |
| `stopQuery` issues `StopQueryExecution` with the id | **moved** |
| `runStatementToCompletion` stops on the first terminal state, honours `signal`, and returns `ABANDONED` | **kept** — the loop never left the browser |
| `getTableDdl` picks `SHOW CREATE VIEW` for a view, joins rows, caps at 999 | **kept** |
| `getDatabase` maps `EntityNotFoundException` to `NotFound` | **moved** (404); **kept** as "a 404 envelope is `code: 'NotFound'`" |
| `listTables` paginates past the page cap | **kept** on the client, now over the API's `nextToken` (FR-008) |
| `listTables` maps `EntityNotFoundException` to an empty success | **moved** |
| every service never throws | **kept**, extended to a non-envelope gateway body (SPEC-197 FR-007) |

#### Acceptance Criteria:

- [ ] Every exported signature in `athena.service.ts` and `glue.service.ts` is unchanged: `runQuery`,
      `getQueryStatus`, `getQueryResults`, `stopQuery`, `runStatementToCompletion`, `getTableDdl`,
      `isTerminalState`, `isAbandoned`, `ABANDONED_CODE`, `getDatabase`, `listTables`. `features/catalog/index.ts`
      is unchanged.
- [ ] `runQuery`'s `outputLocation` parameter is **deleted** — no production call site supplies it
      (verified: `useTabRuns` twice and `useExploration` pass `{sql, username}`;
      `runStatementToCompletion` forwards `{sql, database, username, signal}`), and it can no longer be
      honoured once FR-002 derives the location from the verified claim. `username` stays on the
      signature so the call sites are untouched, and is **not sent** — a test asserts the request body
      contains neither key.
- [ ] `catalog.types.ts` and `catalog.format.ts` are **not edited**. The wire types are generated; the
      services map wire → domain (`nextToken: null` → `undefined`, raw type → `normalizeColumnType`).
- [ ] The eight hooks and both workspaces are unchanged, and **`queryExecutionHooks.test.ts`,
      `useSchema.test.tsx`, `useQuerySpaces.test.ts`, `useExploration.test.ts` and
      `useExplorationTabs.test.ts` are unchanged byte for byte** — they mock the service module, so
      they cannot see the transport. That is the property being demonstrated and the cheapest proof of
      it. The declared exception is FR-010 AC4's retry change, which touches `useExploration.ts`'s
      query options and one assertion.
- [ ] **Exactly one assertion in the existing suites is deleted** — `catalogServices.test.ts`'s
      *"honors an explicit outputLocation (SPEC-055 shared routing)"*, whose subject is the parameter
      AC2 removes — and the table above is honoured row by row for every other. The deletion is named in
      the table, in this criterion and in the delivery doc, which reproduces the table. A blanket "no
      assertion is deleted" over a diff that deletes one is how the next reader stops trusting the
      table.
- [ ] `npm run test:coverage` still meets the portal floors (91/86/89/93) and `pytest lambdas/` the 95
      floor. A port moves logic across languages and must move coverage with it; a floor met by
      deleting the tests that moved passes on one side and sinks the other.

### FR-013: What comes out of the browser

#### Description:

The catalog surface is the first feature whose port removes AWS SDK packages. It is worth doing here
rather than banking it for SPEC-202, because a dependency that is still installed is a dependency
something can still import.

#### Acceptance Criteria:

- [ ] `apps/portal/src/lib/athenaClient.ts` and `lib/glueClient.ts` are **deleted** — nothing else
      imports them (verified). A repo grep for `getAthenaClient` and `getGlueClient` returns nothing.
- [ ] `@aws-sdk/client-athena` and `@aws-sdk/client-glue` are removed from
      `apps/portal/package.json` and the lockfile. A test asserts neither resolves, and `npm run build`
      is what catches a straggling import.
- [ ] `athena.service.ts` and `glue.service.ts` import neither `withCredentialRetry` nor
      `lib/userSpace`. `lib/credentialRetry.ts` and `lib/userSpace.ts` are **not deleted** — S3 and SQS
      still use both (SPEC-198/200/202).
- [ ] `athenaWorkgroup` is removed from SPEC-192's runtime-configuration key set, from
      `.env.example`, and from the deploy wiring, and its removal is caught by SPEC-192's key-set
      agreement tests with no new mechanism. The value now lives once, as the API Lambda's
      `ATHENA_WORKGROUP`.
- [ ] The browser makes **zero** requests to `athena.*.amazonaws.com` and `glue.*.amazonaws.com`,
      asserted live in Phase 5 from the network panel. `connect-src` is not edited here (SPEC-194
      derives it, SPEC-202 finalises it); a host still listed but never fetched is inert, and removing
      it early would make this spec responsible for a CSP change it cannot verify end to end.

---

## Data Model

### The wire — Python, the single declaration

```python
# lambdas/api/apicommon/contract.py  (additions)

QueryState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]

class StartQueryRequest(TypedDict):
    sql: str                       # opaque to the API (Premise 2); byte-identical to QueryString
    database: str | None           # omitted -> QueryExecutionContext is not sent at all (SPEC-077)

class StartQueryResponse(TypedDict):
    queryExecutionId: str

class QueryStatusResponse(TypedDict):
    queryExecutionId: str
    state: QueryState
    stateChangeReason: str | None  # Athena's engine text, VERBATIM. Mapped by errorMessages.ts,
                                   # rendered by nothing, logged by nothing (FR-003, FR-011).
    dataScannedBytes: int | None   # null while non-terminal — never 0 (SPEC-181)
    engineExecutionTimeMillis: int | None
    outputLocation: str | None

class QueryColumnWire(TypedDict):
    name: str
    type: str                      # Athena's raw type; normalizeColumnType stays client-side

class QueryResultsResponse(TypedDict):
    columns: list[QueryColumnWire]
    rows: list[list[str | None]]   # null is SQL NULL; "" is the empty string (FR-004)
    nextToken: str | None

class GlueColumnWire(TypedDict):
    name: str
    type: str

class GlueTableWire(TypedDict):
    name: str
    columns: list[GlueColumnWire]
    tableType: str | None
    location: str | None

class TablesResponse(TypedDict):
    items: list[GlueTableWire]
    nextToken: str | None

# ErrorCode gains exactly one member: "QueryNotFinished" -> 409 (FR-005).
```

The domain types the hooks consume — `QueryStatus`, `QueryColumn`, `QueryResultPage`,
`GlueTableSummary`, `DatabaseSchema` in `features/catalog/catalog.types.ts` — are **unchanged**. The
services map wire → domain. That mapping is the whole reason no hook is edited.

## API / Interface Contract

```ts
// apps/portal/src/features/catalog/athena.service.ts — signatures UNCHANGED.
// Only the innards move: withCredentialRetry(getAthenaClient, …) -> apiRequest(…).

export async function runQuery(p: {sql: string; username: string; database?: string}):
  Promise<ServiceResult<{queryExecutionId: string}>>;      // `outputLocation` param DELETED (FR-012)

export async function getQueryStatus(queryExecutionId: string): Promise<ServiceResult<QueryStatus>>;
export async function getQueryResults(p: {queryExecutionId: string; nextToken?: string; maxRows?: number}):
  Promise<ServiceResult<QueryResultPage>>;
export async function stopQuery(queryExecutionId: string): Promise<ServiceResult<void>>;

// glue.service.ts — signatures UNCHANGED; listTables walks the API's nextToken internally.
export async function getDatabase(databaseName: string): Promise<ServiceResult<{name: string}>>;
export async function listTables(databaseName: string): Promise<ServiceResult<GlueTableSummary[]>>;
```

## Environment Variables

Removed from the SPA (SPEC-192's runtime configuration, `.env.example`, and the deploy wiring):

```
VITE_ATHENA_WORKGROUP / runtimeConfig `athenaWorkgroup`   # -> the API Lambda, below
```

Added to the API Lambda (**required** — raises at first read, never defaults):

```
ATHENA_WORKGROUP=<the shared Athena workgroup name>   # var from infra/modules/analytics' output
```

`USER_SPACE_BUCKET` already exists (SPEC-197). No other variable moves, and no `VITE_*` is added.

## File & Folder Structure

```
lambdas/api/
├── apicommon/
│   └── contract.py                  # + six Route rows, the wire types, QueryNotFinished
├── routes/
│   ├── athena.py                    # NEW — start, status, results, stop
│   └── catalog.py                   # NEW — get-database, list-tables
├── test_athena_routes.py            # NEW — FR-002/003/004/005/006, incl. the message-not-name case
├── test_catalog_routes.py           # NEW — FR-008, incl. both LF denial shapes
└── test_api_no_waiting.py           # NEW — FR-007's sweep, verified by a deliberate violation

apps/portal/src/
├── lib/
│   ├── athenaClient.ts              # DELETED
│   ├── glueClient.ts                # DELETED
│   └── errorMessages.ts             # + QueryNotFinished code rule; − the match rule it replaces
└── features/catalog/
    ├── athena.service.ts            # rewritten innards, unchanged signatures
    ├── glue.service.ts              # rewritten innards, unchanged signatures
    └── catalogServices.test.ts      # rewritten against apiRequest; dispositions honoured
```

## Implementation Phases

### Phase 1: The wire

- The six `Route` rows, the wire types, `QueryNotFinished` and its 409, in `contract.py`; regenerate.
- FR-004's nested-list vocabulary case against SPEC-197's generator, first — if `list[list[str |
  None]]` does not emit, nothing else in this spec has a type.
- `ROUTE_PLANES` rows and FR-001's flag/plane tests.

### Phase 2: The Athena routes

- `routes/athena.py`: start (identity, bucket and workgroup derived; SQL untouched), status
  (`stateChangeReason` verbatim, null statistics while non-terminal), results (the `+1`, the clamp,
  the header drop, the NULL preservation), stop.
- FR-005's message-not-name mapping, with the MALFORMED_QUERY counter-case.
- FR-011's spans, and the two never-log assertions.

### Phase 3: The Glue routes

- `routes/catalog.py`: get-database (404 on `EntityNotFound`), list-tables (200-and-empty on
  `EntityNotFound`, one `GetTables` per request).
- FR-008's two LF denial shapes, in one file.
- FR-008's rendered-policy no-change diff, and FR-001/FR-007's sweeps verified by violation.

### Phase 4: The ported services

- `athena.service.ts` and `glue.service.ts` over `apiRequest`; the wire → domain mapping;
  `listTables`' internal token walk.
- `errorMessages.ts`: the `QueryNotFinished` code rule, the match rule deleted, the byte-identical
  wording test.
- `useExploration`'s `retry` (FR-010 AC4) — the one declared behaviour change.
- Delete both `lib/*Client.ts`, drop the two `@aws-sdk/*` dependencies, move `athenaWorkgroup`.
- Confirm the five named hook/tab test files are unchanged byte for byte.

### Phase 5: Verification

Real invocations against the deployed API, as a new section of
`docs/testing/arc-b-api-container-e2e.md`. **What nothing offline can prove:** that Lake Formation
authorizes
the assumed-role session at all (LF is not modelled by the IAM simulator, and every offline test here
supplies its own botocore fixture); that a real Athena engine message still matches the wording rules
after a JSON round trip; and that the browser has genuinely stopped talking to Athena and Glue.

- **Sign in fresh, signed out to start.** A signed-in pass never tests the token path. Override
  `visibilityState` before anything else — a hidden Chrome window pauses polling and a healthy query
  reads as hung.
- **The LF positive, and it is the arc's claim — run it FIRST, because it also discharges SPEC-196
  Phase 5 item 4.** Run a real `SELECT` from the Query workspace against the caller's own database and
  confirm rows render: the query succeeding *through the API*, with LF grants untouched and the
  principal now assumed rather than vended, is the observation the whole arc rests on. Record the result
  against SPEC-196 as well as this spec. **There is no CloudTrail step here** — the account's only trail
  records S3 **data** events for the archive bucket alone (`is_multi_region_trail = false`, management
  events for nothing), so an `AssumeRole` event does not exist to read and a query against it returns
  empty whether the tags were stamped or not. The tag observation is SPEC-196 FR-004's and is **not**
  re-asserted here; if it is still owed after SPEC-196's phase, it stays owed.
- **The LF negative, both shapes.** (a) Expand a rail node for a database this user has no `DESCRIBE`
  on → the network panel shows **403** with an envelope carrying `code: "AccessDenied"`, no AWS text
  in `detail`, and the screen shows *"You don't have permission to do that."* — **and no re-login**.
  (b) Run a `SELECT` against a table this user has no `SELECT` on → the status route answers **200**,
  the execution reaches `FAILED`, and the banner reads *"You don't have permission to run that
  query."* Record both status codes; recording only (a) proves nothing about the shape that matters
  more.
- **Foreign vs absent database.** `GET /v1/catalog/databases/{a-stranger's-username}` and
  `GET /v1/catalog/databases/{a-name-nobody-has}`. **Record what each actually returns** — this is the
  no-existence-oracle question (SPEC-113) and it is Lake Formation's answer, not this API's. If they
  differ, that is a finding for SPEC-202's sweep, not a failure of this spec.
- **The first-load race, on the surface it broke.** Open `/explore`, pick a source, and watch the
  network panel through the QUEUED window: **zero** `athena.results` requests until the status route
  reports `SUCCEEDED`. Then force the negative by calling `athena.results` against a running execution
  with `curl` → **409 `QueryNotFinished`**, envelope-shaped.
- **`null` ≠ `''` against real data.** Run a statement producing both in one row
  (`SELECT NULL AS a, '' AS b`), and confirm the raw response body carries `[null, ""]` — read the
  body in the network panel, not the rendered grid, which shows the Value panel's rendering of both.
- **The disclosed SQL.** Copy the statement from *Generated SQL*, then
  `aws athena get-query-execution --query-execution-id <id>` and compare `QueryString` **byte for
  byte** (FR-009).
- **Paging and the row count.** Page a >100-row result forward and back (cached pages, no refetch),
  and let `useResultRowCount` finish — confirm the total and that the walk's requests carry properly
  encoded `nextToken` values.
- **`SHOW CREATE TABLE`.** Open *View DDL* on a real table: one start, N status polls at ~400 ms, one
  results call, DDL rendered. This is the only caller that sends `database`.
- **The load-bearing negative:** with the Query workspace and the Data Explorer both exercised end to
  end, the network panel shows **zero** requests to `athena.*.amazonaws.com` and
  `glue.*.amazonaws.com`.
- **`logs/service=api/`**: one record per route with `env: "prod"`, a real build sha (neither empty
  nor `0.0.0`), `route_id` and `actor`; and **absent** — the SQL text, any `stateChangeReason`, any
  result cell, any bearer substring, any email. Records arrive on the 10-minute sweep; wait for it
  rather than concluding from an empty query.
- **Cold start:** confirm the first invocation after a deploy succeeds (SPEC-137's precedent — a layer
  imported and not attached deploys clean and fails at import).
- **Safari** at desktop, since that is the browser in use; a Chromium pass corroborates and **cannot**
  discharge. Record it as such.
- **Recorded as OWED, not discharged:** an execution-ownership check (Out of Scope / Premise 5), and a
  429 mid-walk observed live — account throttling cannot be staged, so FR-007's degradation stays
  unit-tested only.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row (status only); the delivery doc at
  `docs/spec-delivery/SPEC-199-the-catalog-surface-athena-and-glue.md`, carrying FR-012's disposition
  table.
- **`decisions.md` entries**, then **one line each** in CLAUDE.md's Key Decisions:
  1. *The polling loop stays in the browser, and the API makes exactly one AWS call per request* —
     with the computed ceiling (a 5-minute query is 10× a non-raisable 29-second integration limit),
     the four loops that stay, and SPEC-198's free-name route named as the arc's one exception.
  2. *Results are read only at `SUCCEEDED`, and the API maps that state by MESSAGE, never by name* —
     appended to the existing 2026-08-16 entry rather than filed separately, recording that the
     client-side guard is kept, that its test now asserts on the CALL because the screen would look
     right either way, and that the client rule becomes a `code` rule for the first time.
  3. *`stateChangeReason` rides a 200 and is mapped client-side* — that the API returning a machine
     code (SPEC-197) and passing engine text through as data are not in tension, and that swallowing
     it would silently retire six authored sentences.
  4. *Neither the SQL statement nor the engine reason may be a log field* — appended to the field
     rule's existing entry (SPEC-130), because both routinely quote a user's own cell values, and the
     `error.stack` exemption does not cover a field a call site chooses to emit.
- **Correct the stale live-check instruction** in CLAUDE.md's Data Explorer note: with
  `apiRetryPolicy('athena.start') === false`, a failing apply issues **one** `StartQueryExecution`,
  not two, so "count executions on a statement that SUCCEEDS" no longer describes the app.
- A superseded marker wherever a doc still says the browser calls Athena or Glue directly — the
  `architecture.md` *Analytics* section, and the arc entry in `ARCS.md`.
- Component-inventory: `docs/component-inventory/query-feature.md` (or the catalog area file matching
  the path) — `athena.service.ts` and `glue.service.ts` rows rewritten to say "through the API";
  `foundations.md`'s `athenaClient.ts` / `glueClient.ts` rows **removed**.
- The `ARCS.md` arc entry updated with what this spec found — in particular whether a foreign and an
  absent database are distinguishable through Lake Formation, which Phase 5 measures and no offline
  test can.
- **Help sweep: nothing user-facing changes.** Same workspaces, same wording — the one sentence that
  moves house (`QueryNotFinished`) is asserted byte-identical. Record that explicitly and skip.
