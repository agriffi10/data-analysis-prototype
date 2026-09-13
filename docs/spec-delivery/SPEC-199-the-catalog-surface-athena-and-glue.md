# Completed Spec — SPEC-199: The Catalog Surface — Athena & Glue

## What was completed?

The six calls everything analytical rides on — `StartQueryExecution`, `GetQueryExecution`,
`GetQueryResults`, `StopQueryExecution`, `GetDatabase`, `GetTables` — moved behind the API. No hook,
component or user-visible behaviour changed, which is the claim the spec was built to make checkable.
`@aws-sdk/client-athena` and `@aws-sdk/client-glue` left the browser with them, so `client-sqs` is the
only AWS SDK the app still ships.

Delivered in three PRs: the wire, the handlers, then the cutover.

- **`apicommon/contract.py`** — the six routes, `QueryState`, the wire types, `QueryNotFinished`
  (409) and `QuerySyntaxError` (400), plus **path templates**: a `Route` may now carry `{placeholder}`
  segments, and the table refuses a malformed placeholder or two overlapping templates at declaration.
- **`lambdas/api/routes/athena.py`** — start (identity, bucket and workgroup derived server-side; the
  SQL untouched), status (`stateChangeReason` verbatim on a 200, `null` statistics while
  non-terminal), results (the `+1` overfetch, the 1000 clamp, the header-row drop, `null` ≠ `""`),
  stop. **`routes/catalog.py`** — get-database (404 on `EntityNotFound`) and list-tables (200 and
  empty on the same), one Glue call each.
- **`apicommon/config.py`** — `athena_workgroup()`, required with no default.
- **`lib/apiClient.ts`** — `params`, `substitute` and the `UnsendableParameter` code; a templated
  route's parameters are **required by the type**, so omitting one is `TS2554` rather than a literal
  `{queryExecutionId}` on the wire. `test/apiMock.ts` records and exposes them (`paramsFor`).
- **`lib/errorMessages.ts`** — the `QueryNotFinished` and `QuerySyntaxError` code rules, the
  match rule the first replaces deleted, and `USER_FIXABLE_CODES` computed from the rules.
- **`athena.service.ts` / `glue.service.ts`** — same exports, same signatures, `apiRequest` inside.
- **`lib/athenaClient.ts`, `lib/glueClient.ts` and both `@aws-sdk/*` packages** — deleted.
- **`athenaWorkgroup`** — out of the runtime configuration, across every one of its wiring sites in a
  single commit: three key-set agreement tests compare the classification against `deploy-app.yml`
  and `infra/main.tf` in both directions, so no subset of the removal is green. The value now lives
  once, as the API function's `ATHENA_WORKGROUP`.

## FR-012's disposition table — every existing assertion accounted for

Reproduced here because "we moved the tests" is the claim nobody can check a year later. One
assertion was deleted, and it is named.

| Existing assertion (`catalogServices.test.ts`) | Disposition |
|---|---|
| `runQuery` sends the workgroup from the environment | **moved** to Python (`ATHENA_WORKGROUP`) |
| `runQuery` omits `QueryExecutionContext` with no database, sends it with one | **moved** |
| `runQuery` targets `{username}/athenaresults/` | **moved**, and strengthened — see the deviation below |
| `runQuery` honors an explicit `outputLocation` | **DELETED**, the one deletion: the parameter went with it |
| a missing `QueryExecutionId` is a failure | **moved** (500); **kept** as "a 500 envelope is `{success: false}`" |
| `getQueryStatus` maps state, reason, statistics and output location | **both** — Python the botocore shape, TS the wire shape |
| a missing `Status.State` defaults to `QUEUED` | **moved** |
| the first-page header row is dropped and a continuation's is not | **moved** |
| the `+1` overfetch and the 1000 clamp | **moved** |
| an absent `VarCharValue` is `null`, a present empty one is `''` | **both** — Python on the serialised body, TS on the parsed page |
| `stopQuery` issues `StopQueryExecution` with the id | **moved** |
| `runStatementToCompletion` stops on the first terminal state, honours `signal`, returns `ABANDONED` | **kept** — the loop never left the browser |
| `getTableDdl` picks `SHOW CREATE VIEW` for a view, joins rows, caps at 999 | **kept** |
| `getDatabase` maps `EntityNotFoundException` to `NotFound` | **moved** (404); **kept** as "a 404 envelope is `code: 'NotFound'`" |
| `listTables` paginates past the page cap | **kept**, now over the API's `nextToken` |
| `listTables` maps `EntityNotFoundException` to an empty success | **moved** |
| every service never throws | **kept**, extended to a non-envelope gateway body |

Five test files are byte-for-byte untouched — `queryExecutionHooks.test.ts`, `useSchema.test.tsx`,
`useQuerySpaces.test.ts`, `useExplorationTabs.test.ts`, `queryPure.test.ts` — along with eight hooks
and both workspaces. `useExploration.test.ts` gains one assertion, the exception FR-010 AC4 declared.

### Deliberate deviations

- **`QuerySyntaxError` (400) is a code the spec did not ask for.** Athena refuses some statements at
  submit and accepts others that then fail; the user typed the same mistake either way, but the first
  group fell to `InvalidRequest` and read *"Something went wrong. Contact the Administrator."* The
  generic sentence is now reserved for what a user cannot act on, and `USER_FIXABLE_CODES` is computed
  from the rules so a guard holds that, not a reviewer. Its sentence is asserted equal to the
  failed-execution path's, so the two cannot drift.
- **FR-002's disagreeing fixture was unexpressible, and what replaced it is stronger.** A body or
  query naming another user is refused by the contract before a handler runs — the declared body is
  `{sql, database?}` and the route declares no query — so the assertion is that the wire has
  **nowhere** to name a user. The location is proved to follow the claim by driving two different
  tokens through one route; a single-token fixture cannot tell a route reading the claim from one
  reading a constant.
- **FR-007's sweep lives in `test_api_thinness.py`, not a new `test_api_no_waiting.py`.** It is the
  same population as the existing paginator sweep, and two files would have meant two module lists.
- **The refusal of a path parameter that is not one segment is client-side.** The server cannot tell
  such a path from one a caller legitimately typed — by the time it matches, the separator is a
  separator. Both sibling routes sit on the same plane under the same assumed identity, so a caller
  reaches nothing a direct request would not give them; whether `rawPath` preserves the encoding and
  would allow the same check server-side is **not measured**, and the comments say so.

## What changed from earlier specs?

- **`runQuery` lost its `outputLocation` parameter** (SPEC-055's shared routing). No production call
  site supplied it, and it cannot be honoured once the location is derived from the verified claim.
  `username` stays on the signature so no caller changed, and is not sent.
- **`useExploration`'s start query no longer retries.** It inherited the app's `retry: 1`, so a
  failing apply issued two `StartQueryExecution` calls a second apart — two executions and two bills
  for one gesture. It now takes `apiRetryPolicy('athena.start')`, which is `false`. That line was
  invisible to the whole suite (`renderWithProviders` sets `retry: false` on every test client), so
  the assertion drives a failing start against a client that *would* retry. The guard named after the
  original incident could not see the module either — it filtered to modules containing `apiRequest`,
  and `useExploration` reaches the API through a service; widened to every module setting a retry.
- **`errorMessages.ts`' `invalid_query_execution_state` match rule is gone**, replaced by a `code`
  rule on `QueryNotFinished`. The ambiguity that forced a message rule is resolved at the one layer
  holding the message, and a code rule outranks every message rule.
- **`apicommon/config.py` no longer claims a credential scrub exists.** There is none. What holds is
  that a handler is never given a credential, and a test asserts the request context carries nothing
  credential-shaped.
- **`docs/testing/e2e.md`'s instrument 2 and its `retry: 1` trap row were both stale on merge** —
  the catalog no longer sends `x-amz-target`, and one failing apply is now one call. Both corrected
  here.

## What is owed

**Phase 5 in full.** Nothing offline can settle that Lake Formation authorizes the assumed-role
session (LF is modelled by no IAM simulator, and every offline test supplies its own botocore
fixture), that a real engine message still matches the wording rules after a JSON round trip, or that
the browser has stopped talking to Athena and Glue. The steps are in
[`docs/testing/e2e.md`](../testing/e2e.md) §4.3 and §4.5, and the rows are in
[`owed.md`](../testing/owed.md) — including **SPEC-196 Phase 5 item 4**, which this spec inherited and
therefore still owes.

**The execution-ownership exposure is preserved, not introduced.** Athena authorizes by workgroup and
this deployment has one, so a browser holding another user's execution id can read that execution
exactly as it could before. The span's `actor` and `execution_id` are the whole mitigation, and a real
fix needs an execution→owner record that does not exist.

> **Superseded by SPEC-232 (2026-09-10): closed.** The output location Athena records is that
> record. Every route that names an execution proves it is the caller's first, and answers an
> unknown id and someone else's with one 404:
> [`decisions/identity-and-access.md`](../decisions/identity-and-access.md#an-execution-id-is-a-claim-and-every-route-that-names-one-proves-it-first-spec-232).

## Help & guides

**Nothing user-facing changed.** Same workspaces, same wording; the one sentence that moved house
(`QueryNotFinished`) is asserted byte-identical to the rule it replaced. The one *addition* —
`QuerySyntaxError` — replaces a generic sentence with an existing authored one and adds no capability
and no flow, so no guide describes anything that is now untrue. Swept and skipped.

## Verification

Green locally on each PR: `pytest lambdas/` (1682, 87.30% against a floor of 85; both new route
modules at 100%), mypy, ruff, 2238 vitest, `tsc -b`, ESLint, Prettier, `check:bundle`,
`validate_docs.py`, and the contract regenerating byte-identical. Two fresh-context diff reviews per
PR, each finding defects in the previous round's fixes; every guard the reviews questioned was
plant-verified rather than argued. Deferred to a signed-in session: everything under *What is owed*.
