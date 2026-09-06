# Completed Spec — SPEC-221: Results Conversion, the Plane and validate-authorize

## What was completed?

An eighth control plane, and **nothing a user can reach**. It will write a finished Athena
execution's result set into a space the actor may write to, as Parquet, JSON or Excel; this spec
built the plumbing and the front door, and the machine ends at a `Placeholder` having written
nothing. SPEC-222 adds the converter, SPEC-223 the browser.

- **`infra/modules/results-conversion/`** — FIFO request queue and its own FIFO DLQ (content-based
  dedup off on both), an EventBridge Pipe at batch 1 `FIRE_AND_FORGET`, a Standard state machine,
  and one shared execution role. Wired into `local.drained_dlq_names`, `lambda_deployed_names`,
  the API's queue map (`request_queue_arns` 9 → 10) and the user-space bucket policy's principal
  allowlist — the last of those **before the plane has any S3 write grant**, because an explicit
  resource-policy Deny beats an identity Allow and a plane missing from the list is denied by the
  bucket however correct its own grants are.
- **The machine** — `ValidateAuthorize → Validated → DescribeResults → Described → Placeholder →
  Succeeded`, with `ValidateFailureSeed`/`RequestFailureSeed → RecordFailure → NotifyFailure →
  Failed` complete from day one, a top-level `TimeoutSeconds` and its EventBridge `TIMED_OUT` rule.
  `Validated` and `Described` are the ASL/verb cross-check points: a Pass naming each key fails the
  build when a verb renames one, where a Task-to-Task chain would notice nothing.
- **`rccommon`** — this plane's wording, its closed reason set, its destination rules and its
  authorizer. `cpcommon` supplies every algorithm; a test asserts the layer defines no CAS loop,
  no lock, no queue parser and no message resolver.
- **`cpcommon.results.user_results_prefix(bucket, username)`** — where a *user's own* queries write,
  which is a different fact from `results_location` (where a plane's DDL writes) and deliberately
  not merged with it. The API's `output_location` is now a call to it, and validate-authorize
  proves ownership against the same bytes.
- **The verbs** — validate-authorize authorizes the destination space, contains the key inside it,
  refuses the app-managed folders, and proves the execution is the actor's by the path Athena
  recorded; describe-results reads the columns and types from one `GetQueryResults` and the size
  from one `HeadObject`, and refuses what the converter cannot hold. notify-failure carries both
  doors, the timeout one reading the event's own input.
- **The two properties everything downstream rests on** — the input is the execution's result
  object rather than the source table, and an execution is the actor's iff Athena wrote it under
  the one shared results prefix — are recorded once, in
  [`decisions/control-planes.md`](../decisions/control-planes.md#a-conversion-reads-the-result-never-the-source-and-ownership-is-a-question-about-a-path-spec-221).
- **The API** — `ResultsConversionEnqueueRequest`, `POST /v1/enqueue/results-conversion`, the
  `results-conversion` queue, FIFO keys (group is the actor's username, dedup is the request id)
  with a golden vector, and the generated TypeScript.

## What changed from earlier specs?

- SPEC-218's builder is what the refused-destination set is derived from: `cpcommon.app_managed`
  gained `SPACE_FOLDERS`, the three folders that live inside a space's own bucket, so this plane's
  refusal is a superset of what that module declares rather than a fourth copy of the list.
- The plane's protected-folder rule is **any-depth in both buckets**, which is stricter than the
  browser's picker in a personal space. That is deliberate: it mirrors the execution role's Deny,
  whose IAM wildcard matches `/`, so a validator that accepted a deeper key would turn a named
  refusal into an `AccessDenied` at the write.
- FR-006's "a request refused before identity … is dead-lettered" was **corrected in the spec**: the
  Pipe is `FIRE_AND_FORGET`, so a message whose execution started is gone from the queue whatever
  the execution does. `conversion_timed_out` was added to the same list, as file-send's
  `send_timed_out` is.
- No `architecture.md` ADR row. An eighth plane following the established pattern is not a change
  to the system's shape; the plane counts in `architecture.md`, `CLAUDE.md` and the register's
  router were updated instead.

## Three defects the reviews and CI found

- **The derived results key was not contained.** The ownership check is a `startswith`, so a
  recorded location of `.../athenaresults/../../bob/x.csv` passed it while naming another user's
  object. Nothing writes such a location today, but this is the one place an S3-supplied path
  becomes a key the converter will read. It now refuses a dot segment.
- **An unhashable space kind raised `TypeError`.** `kind not in SPACE_KINDS` hashes the value, so a
  request naming a list crashed the membership test itself where a named refusal was the honest
  answer. Three older planes carry the same shape — `focommon`, `fscommon` and `arcommon`'s authorizers
  each run `kind not in SPACE_KINDS` unguarded — and are left to their own change rather than
  widened into this one.
- **Nothing could see a dangling `Next` or an unreachable state in any plane's ASL.** Step Functions
  refuses an unreachable state at `CreateStateMachine`, so that is a red first apply with nothing
  local to catch it. A reachability and dangling-target check now runs over all eight templates,
  with a positive control; both edges were mutation-tested against a real template.

## The cutover guard, which refused this plane on four separate legs

The frozen pre-cutover parity fixture was built for a one-time event and kept running afterwards,
so its preconditions had quietly become claims about every future change — none observable until
something grew. Its floor, its extractor and its unknown-field refusal each refused this plane for
doing what a plane does, and its `environment` leg — the fourth — was **retired** with its replacement named
(`test_fleet_environment.py`, live rather than frozen) after two attempts to patch it. The full
account is in
[`decisions/gates-and-tests.md`](../decisions/gates-and-tests.md#a-parity-fixture-becomes-a-floor-once-the-cutover-it-guarded-is-closed-2026-09-05).

## Verification

`pytest lambdas/` green by exit code, `ruff`, `mypy`, `scripts/validate_docs.py`,
`scripts/validate_app_managed_paths.py`, `tofu fmt -check -recursive`, `tofu validate`, and the
portal's formatter, linter, suite and build. Four fresh-context reviews: the plan, the PR grouping,
and the diff twice — a security frame that planted 21 mutants against the authorizer (17 killed,
two survivors fixed, two confirmed-redundant belts) and a build-and-run frame that built the real
container image and drove the machine end to end in Python.

**In production, after the merge:** the cold-start probe reached
`results-conversion-validate-authorize` on the deployed artifact and it refused an empty payload
with a `TerminalError`; both queues, the Standard machine and the three functions exist; the
execution role carries exactly eight statements with no `s3:PutObject` Allow; and
`simulate-principal-policy` returns `explicitDeny` for a write under `athenaresults/`, `archive/`,
`shared_tables/` and `user_settings/` against `implicitDeny` for an ordinary path — run **one
resource per call and read as JSON**, because a multi-resource simulate printed with
`--output text` reports the verdict on the first row only, which reads as four passes for one — so the Deny
mirror discriminates rather than merely existing, and will still bite when SPEC-222 adds the write.

**Owed:** the live request through the API and the per-code refusals. This plane has no browser
surface until SPEC-223, so they need a hand-driven authenticated call; recorded in
[`testing/owed.md`](../testing/owed.md).
