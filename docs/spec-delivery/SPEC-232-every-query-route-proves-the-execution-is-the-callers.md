# Completed Spec — SPEC-232: Every Query Route Proves the Execution Is the Caller's

## What was completed?

- **Status, results and stop prove ownership before they answer or act.** Each one reads the
  execution through `_owned_execution` in `lambdas/api/routes/athena.py` before any other Athena
  call. An execution whose recorded output location is not under the caller's own results prefix
  gets the same 404 `NotFound` as an id Athena does not know, so within the portal's workgroup the
  API cannot be used to ask whether an execution exists. An id from AWS's `primary` workgroup still
  gets IAM's 403. The span's `execution_ownership` attribute records which case it was.
- **One predicate, shared.** `cpcommon.results.owned_results_key` holds the rule. Results-conversion's
  validate-authorize now calls it, with its behaviour unchanged, so the rule exists in one copy.
- **A guard derived from the contract.** A test covers every route whose path names
  `{queryExecutionId}`, drives each one against a foreign execution and an unknown id, and fails when
  a path, query or body field it does not expect names an execution. The one it expects outside
  those routes is results-conversion's body field, which that plane proves with the same predicate.
- **The record matches.** The register entry *An execution id is a claim, and every route that
  names one proves it first* and its Fences bullet in `docs/decisions/identity-and-access.md`, the
  trap on `lambdas/info/planes/api.md`, and supersede markers in SPEC-199's spec and delivery doc,
  where the old premise was stated.
- Nothing a user sees changed, and there was no browser, contract, IAM or infrastructure change.

### Deliberate deviations

- **Completed with its live check still owed** (Andrew, 2026-09-16). The code merged as #730 and
  deployed on 2026-09-13. The live check was put off that day, when the session had no signed-in
  tab, and has not run since. It stays in `docs/testing/owed.md`, and the *Accepted exposure* row
  there still retires only when it runs.

## What changed from earlier specs?

- **SPEC-199's recorded exposure is closed in code.** Its premise, that a fix needed an
  execution-to-owner record, was false: the output location Athena records on each execution is
  that record.
- **Unknown ids answer consistently.** Before this spec an unknown id got 500 from status, 400 from
  results and 200 from stop. Status and results now answer 404, and stop answers 404 before it
  stops anything.
- **Stop makes a second Athena call**, `GetQueryExecution`, before `StopQueryExecution`.

## Verification

- **Merged on green CI as #730**, after its local gates and five fresh-context reviews: the spec,
  the plan, the PR grouping, and two diff reviews in the security frame and the regression frame.
  The PR body lists the gates and the plants, each seen red and then reverted.
- **Live check: owed.** The steps are the SPEC-232 row in `docs/testing/e2e.md` §4.3. The two-user
  version is in `docs/testing/owed.md` under *Needs a second (or third) account*.
