# Spec: A Run That Ends on an Error No Catch Takes Still Tells the User

**ID:** SPEC-236
**Status:** Cancelled
**Last Updated:** 2026-09-16
**Depends On:** SPEC-152, SPEC-161, SPEC-201

## Why this spec was cancelled

**Andrew's decision, 2026-09-16: the work is not being done.** The spec was never built. The gap it
describes is still live: a run ending on `States.DataLimitExceeded` or `States.Runtime` reaches no
notifier. The gap is recorded as accepted in `docs/decisions/control-planes.md`, in the entry *Every
plane notifies on a pre-verb failure*, together with the traps a later fix would meet. The rest of this file is the Draft as it stood.

## Overview

Every control plane reports its outcome to the user as a notification, because the user has no
other way to learn what happened. When a failure is taken by a state's `Catch`, it goes to the
plane's `NotifyFailure` state. When a run is stopped by the machine's own `TimeoutSeconds`, it
reaches the same Lambda through an EventBridge rule on `TIMED_OUT`. Two Step Functions errors reach
neither:

- `States.DataLimitExceeded` is raised when a state's payload passes 256 KB. `States.ALL` does not
  match it, and no catcher in the fleet names it.
- `States.Runtime` cannot be caught by anything.

A run that raises either one ends FAILED, and no rule matches FAILED, so nobody tells the user. On
archive and file-ops this can happen after their files have been moved or deleted. The machines
are built so that neither error is raised, and tests compute the payload bounds that keep it so.
This spec is the second line of defence, for when a bound is wrong.

The spec adds a second EventBridge rule to every plane. It matches FAILED only when the
execution's error is one of those two names. Each plane's notify-failure Lambda then tells the user
in a sentence that makes no claim about how far the request got.

### What was checked, and how

Read from the code at `d42a3b42`, and from the vendor pages named.

- **The two errors, from the vendor.** The
  [error-handling page](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)
  says `States.ALL` cannot catch the `States.DataLimitExceeded` terminal error or the `Runtime`
  error types. It says `States.DataLimitExceeded` can be caught or retried by naming it in
  `ErrorEquals`, and that `States.Runtime` is not retriable and always fails the execution.
- **The fleet's catchers.** Parsed as JSON, the eight `infra/modules/*/state-machine.asl.json.tftpl`
  files carry 96 catchers, every one of them `States.ALL`. They also carry 93 retriers, which name
  the Lambda service errors and `TransientError`. None of the 189 names either error.
- **The event carries the error's name.** The
  [EventBridge integration page](https://docs.aws.amazon.com/step-functions/latest/dg/eventbridge-integration.html)
  lists `detail.error` and `detail.cause` in the event structure for
  `Step Functions Execution Status Change`. Its FAILED example carries the execution's error, and
  its TIMED_OUT example carries `States.Timeout`. A pattern can therefore filter on `detail.error`.
- **A caught failure cannot carry either name.** Every machine's terminal `Fail` state sets a
  static `Error`: `ArchiveFailed`, `DataQualityCheckFailed`, `FileSendFailed`,
  `ResultsConversionFailed`, `ProvisioningFailed` (shared-spaces), `TableBuildFailed` and
  `TableShareFailed`. file-ops' `Failed` sets none. A run that reached `NotifyFailure` ends at that
  state, so its FAILED event names one of those, or nothing, and never either of the two.
- **The six existing doors.**
  - archive, file-ops, file-send, results-conversion, table-builder and table-share each carry
    `aws_cloudwatch_event_rule.execution_timed_out`, named `${local.state_machine_name}-timed-out`.
    It matches `status: ["TIMED_OUT"]` and `stateMachineArn: [local.state_machine_arn]`, and
    targets `module.functions["notify-failure"]` through its own `aws_lambda_permission`.
  - Each handler picks the door on `detail-type == "Step Functions Execution Status Change"` alone
    and never reads `detail.status`. **So a FAILED event delivered to today's door would be worded
    as a timeout.**
  - Every door recovers the actor with `cpactor.trusted_actor` on the identity block in
    `detail.input`. When EventBridge omits the input, archive, file-ops and file-send fall back to
    `states:DescribeExecution` through `cpcommon.events.timed_out_execution_input`.
    results-conversion, table-builder and table-share log a no-op instead, and the roles of the
    first two are pinned by tests to hold no such grant.
- **data-quality and shared-spaces have no door.** Neither sets a `TimeoutSeconds`, neither has a
  rule, and both handlers read only the ASL request object. A status-change event would find no
  actor and end in their no-verified-actor no-op.
- **Every queue body carries the identity block.** `lambdas/api/apicommon/enqueue.py` is the one
  path the enqueue routes take to `SendMessage`, and it stamps `identity` on every body. So every
  plane's execution input carries the block.
- **Four planes tell the user of success before their last state.**
  - archive sends `NotifyArchived` or `NotifyRestored`, then runs a Pass.
  - data-quality sends `AssembleReport`, then runs `DropTempTables` and a Pass.
  - table-builder sends `ExecuteDdl`, `ApplyRefresh` or `DiffSchema`, then runs `ReleaseRefreshLock`
    and a Pass.
  - table-share sends a per-recipient `CreateTable`, then collects the Map's results and runs
    `ShapeSummary`.

  An uncaught error after those states ends a run the user was already told had succeeded.
  table-share's notifier names a `States.DataLimitExceeded` on the Map's collected results as that
  plane's realistic case.
- **Every plane's failure sentence opens by asserting failure.** Each resolver in the plane's
  `messages` module prefixes its body: "Couldn't archive that: ", "Couldn't share ...: " and so
  on. A sentence rendered through one would contradict a success already delivered.
- **The deploy role scopes EventBridge rules by name.**
  - On archive, file-ops, file-send, results-conversion, table-builder and table-share, `events:`
    rule and target actions are scoped to the exact rule
    `rule/${project_name}-*-<plane>-orchestrator-timed-out`.
  - data-quality has no `events:` statement.
  - shared-spaces' `SharedSpaceScheduleManage` is scoped to `rule/${project_name}-*-shared-space-*`,
    which already matches a new name.
  - `lambda:AddPermission` is already granted on every plane's functions.
  - `archive/stepfunction.tf` records that the `events:` grant had to ship one PR ahead of its rule.
- **Distributed Map children cannot pass the door.** archive (three Maps), file-ops, file-send and
  table-share run their Distributed Maps as STANDARD children.
  - The vendor documents a child's labelled state machine ARN, `stateMachine:<name>/<MapRunLabel>`,
    for metrics. It does not document what a child's status-change event carries.
  - Every one of those Maps reads from an S3 `ItemReader` with no `ItemSelector`. Its
    `ItemBatcher.BatchInput` carries only `traceparent`, plus `requestId` on the first five.
  - So a child's input is never the Pipe's SQS record and never carries an identity block. Even an
    event that named the parent's exact ARN could not be attributed to anyone.
- **The existing fleet gate reads one pattern.** `lambdas/test_timeout_doors_fleet.py` takes
  `text.split("event_pattern")[1]`, which is the first pattern, and asserts `"FAILED" not in` it. A
  second rule placed after it is never read. The gate's population is the ASLs that set a
  `TimeoutSeconds`, which is six.
- **Measured in production with single read-only calls, and what was not.**
  - `describe-execution` on two real caught failures reports `error: "TableShareFailed"` for
    table-share and `error: "DataQualityCheckFailed"` for data-quality. Each is the plane's static
    `Fail` name, as the filter assumes.
  - The session's auto-mode classifier refused `list-executions` for file-ops, although the same
    call for data-quality ran, and it refused one compound read. So two things are still FR-007's
    to measure: what file-ops' error-less `Fail` reports, and a Distributed Map child's
    `stateMachineArn`.

### The decisions, made while authoring

- **A second rule per plane, not a widened first one.** The rule is `<machine>-failed-uncaught`.
  Its pattern is `status: [FAILED]`, `stateMachineArn: [<the machine's exact ARN>]` and
  `error: [States.DataLimitExceeded, States.Runtime]`. It targets the same Lambda through its own
  permission.
  - *Widening the `TIMED_OUT` rule with `$or` was rejected.* One rule would carry two meanings, and
    the deploy role grants rules by exact name.
  - *Naming `States.DataLimitExceeded` in every Catch was rejected* (Andrew, 2026-09-14). It would
    leave `States.Runtime` and an overflow on a Pass state silent, and it adds about 96 catchers.
  - *An unfiltered FAILED rule stays forbidden.* Every caught failure ends FAILED after
    `NotifyFailure`, so an unfiltered rule would double-notify every one of them. The filter is what
    lets that reason hold.
- **The handler routes by status inside the door, and re-checks the error.** The door is still
  chosen by detail-type. Inside it:
  - TIMED_OUT keeps today's path unchanged.
  - FAILED takes the new path only when `detail.error` is one of the two names.
  - Anything else is a logged no-op.

  The rule and the handler deploy separately. If the handler trusted the rule, a mistakenly widened
  pattern would word every caught failure a second time.
- **One sentence for the whole fleet, rendered without the plane's prefix.**
  `cpcommon.messages.uncaught_failure_message(operation, check)` returns:

  > Your {operation} stopped with an internal error before it could report how it went. If you've
  > already had a message about it, that message stands. If not, please {check} before trying
  > again.

  - It has no prefix because every plane's prefix asserts a failure, which this door cannot know on
    four planes.
  - It has no Cause, error name or count. A `States.Runtime` Cause is operator text that names
    paths in the state.
  - Each plane supplies its own `{operation}` and `{check}` (FR-005).
- **Actor recovery reuses each plane's timeout path.** The door reads the same identity block. It
  takes the same `DescribeExecution` fallback where the plane already holds the grant, and the same
  no-op where it does not. data-quality and shared-spaces take the no-op form, and neither role
  gains `states:DescribeExecution`. The input is the Pipe's record, the same as a timeout's, and
  EventBridge omits it only above 248 KiB escaped.
- **Dedup is keyed on the execution, on every plane.** Each door's emit passes
  `cpcommon.notify.dedup_id(detail["executionArn"], "uncaught")`.
  - Every status-change event carries the execution ARN, and it is unique per run. So an EventBridge
    redelivery collapses, and a second run's notice does not.
  - *Content-based dedup was rejected.* The sentence carries nothing per request, so a second run
    within the queue's five-minute window, such as a deterministic overflow retried at once, would
    be dropped as a duplicate of the first.
  - *Keying on the body's `requestId` was rejected.* table-share's body carries none, and
    shared-spaces' existing token has a different shape.
- **data-quality's `reportKey` suppression cannot run on this door.** A FAILED event carries no
  state output. The sentence's second clause covers a check whose report was already delivered.
- **The rules deploy only after the handlers can route them.** A FAILED event reaching today's door
  would be worded as a timeout. The handler change is inert until a rule sends it that event, so it
  lands and deploys first, and the rules follow in a later PR.
  - This holds because Deploy Lambdas rolls every function on a push that touches `lambdas/**` or
    `infra/modules/**`, and Deploy Infrastructure applies only on `infra/**`.
  - The Phase 2 merge becomes the notify-failure functions' **rollback floor**. Once the rules
    exist, a `Deploy Lambdas` dispatch at an earlier sha puts back handlers that word a FAILED event
    as a timeout. `lambdas/info/deployment.md`'s rollback section says so.
- **The fence changes its letter, not its reason.** "Never `FAILED`, or every caught failure
  double-notifies" becomes "never an unfiltered `FAILED` …", plus a clause saying the one FAILED
  rule a plane carries matches only the two errors no Catch takes.

## Scope

### In Scope

- The deploy role's `events:` grants for the new rule name on seven planes, in their own PR, merged
  and applied before the rules (FR-001).
- The new rule, target and permission on all eight planes (FR-002).
- Status routing in the six existing doors (FR-003), and a door for data-quality and shared-spaces
  (FR-004).
- `cpcommon.messages.uncaught_failure_message`, and each plane's `{operation}` and `{check}` (FR-005).
- The fleet gate for the new rule, with its fixture corpus. `test_timeout_doors_fleet.py`, and the
  two per-plane tests that copy its first-pattern idiom, change to read every `event_pattern`
  (FR-006).
- The prose that states the old rule or the old gap. That means the Fences in
  `docs/decisions/control-planes.md` and `infra/info/control-plane-shape.md`; a new register entry;
  ADR 27 in `docs/architecture.md`; and the "never `FAILED`" lines in the module READMEs, plane
  pages and `stepfunction.tf` comments. It also means the notify-failure docstrings' "Two Step
  Functions errors never reach it by either door" and "The two doors cannot double-notify"
  paragraphs, their `_is_execution_timeout` docstrings ("The status is NOT re-checked here"), and
  the matching sentence in `test_state_machines_cpcommon.py` (FR-006).
- The rollback floor, as one paragraph in `lambdas/info/deployment.md`'s rollback section.
- The production measurements and the live-check rows (FR-007).

### Out of Scope

- **Any change to a state machine definition,** including naming either error in a Catch. The
  decisions above say why.
- **An uncaught error inside a Distributed Map child.** It fails that child only. The parent's Map
  either tolerates it or fails with `States.ExceedToleratedFailureThreshold`, which the Map's own
  `States.ALL` Catch takes.
- **`states:DescribeExecution` for any plane that does not hold it today.**
- **Reading execution history to suppress the sentence after a success.** Only the sentence's
  second clause reconciles the two messages.
- **Forcing a real uncaught failure in production.** The machines are built so neither error is
  raised, and staging one means changing a machine. The first real occurrence is an `owed.md` row
  (FR-007).
- **Guaranteed delivery.** EventBridge delivers Step Functions events on a best-effort basis, as it
  does for `TIMED_OUT`, and a dropped event means the old silence for that run.
- **An execution ceiling (`TimeoutSeconds`) for data-quality or shared-spaces.**

---

## Functional Requirements

### FR-001: The deploy role may manage each plane's FAILED door

#### Description:

Each plane's deploy-role policy under `infra/modules/base/policies/` grants EventBridge's rule and
target actions on that plane's `-failed-uncaught` rule. The change lands in its own PR, merged and
applied green, before FR-002's resources.

#### Acceptance Criteria:

- [ ] For archive, file-ops, file-send, results-conversion, table-builder and table-share, the
  statement that grants `events:PutRule` lists both
  `rule/${project_name}-*-<plane>-orchestrator-timed-out` and
  `rule/${project_name}-*-<plane>-orchestrator-failed-uncaught`, and no other rule resource.
- [ ] data-quality's policy carries a new statement granting `events:PutRule`, `DeleteRule`,
  `DescribeRule`, `PutTargets`, `RemoveTargets`, `ListTargetsByRule`, `ListTagsForResource`,
  `TagResource` and `UntagResource` on exactly
  `rule/${project_name}-*-data-quality-orchestrator-failed-uncaught`.
- [ ] shared-spaces' policy is unchanged, and `SharedSpaceScheduleManage` still names
  `rule/${project_name}-*-shared-space-*`.
- [ ] The Deploy Infrastructure run for that PR's merge commit on `main` is green before FR-002's PR
  is pushed.

### FR-002: Every plane carries a FAILED door filtered to the two errors

#### Description:

Each of the eight `infra/modules/<plane>/stepfunction.tf` files gains three resources:

- `aws_cloudwatch_event_rule.execution_failed_uncaught`, named
  `${local.state_machine_name}-failed-uncaught`, with the pattern in the interface contract below.
- `aws_cloudwatch_event_target.execution_failed_uncaught`, targeting
  `module.functions["notify-failure"].function_arn`.
- `aws_lambda_permission.execution_failed_uncaught`, with
  `statement_id = "AllowEventBridgeExecutionFailedUncaught"`, principal `events.amazonaws.com`, and
  `source_arn` set to the new rule's ARN.

The six `execution_timed_out` groups are unchanged.

#### Acceptance Criteria:

- [ ] Each of the eight files has exactly one rule whose pattern names `FAILED`. That rule's
  `detail` is exactly `status = ["FAILED"]`, `stateMachineArn = [local.state_machine_arn]` and
  `error = ["States.DataLimitExceeded", "States.Runtime"]`, with no other key.
- [ ] `git diff` shows no line changed inside any `execution_timed_out` resource.
- [ ] The PR's `tofu plan` (or, if CI plans only on merge, the merge run's plan) adds exactly three
  resources per plane, 24 in all, and changes or destroys nothing. If the plan cannot be read
  before the merge, this criterion is recorded as owed on the PR.
- [ ] FR-002 merges only after FR-003 and FR-004 are deployed: the Deploy Lambdas run for their
  merge commit is green.

### FR-003: The six timeout doors route a FAILED event by its status

#### Description:

This covers archive, file-ops, file-send, results-conversion, table-builder and table-share. The
door the handler picks on the detail-type now reads `detail.status`:

- `TIMED_OUT` keeps today's path, sentence and dedup.
- `FAILED` where `cpcommon.events.is_uncaught_failure(detail)` holds takes the new path. It recovers
  the actor exactly as that plane's timeout path does, and sends that plane's FR-005 sentence with
  the execution-keyed dedup id.
- Every other status or error is a logged no-op that sends nothing.

Each handler's `_is_execution_timeout` docstring currently says "The status is NOT re-checked
here". This FR makes that false, and the docstring changes with the code.

#### Acceptance Criteria:

- [ ] Each handler, driven with the vendor's FAILED event shape carrying
  `error: "States.DataLimitExceeded"` and an input whose identity block is valid, sends exactly one
  notification. It goes to that identity's user, and its text equals that plane's FR-005 sentence.
- [ ] The same holds with `error: "States.Runtime"`.
- [ ] Driven with FAILED and `error` set to the plane's own `Fail` name (file-ops: `null`), each
  sends nothing and logs that the failure was caught.
- [ ] Driven with `TIMED_OUT`, each sends today's timeout sentence. One test per plane asserts that
  the timeout sentence and the uncaught sentence differ.
- [ ] Driven with `ABORTED`, each sends nothing.
- [ ] Driven with FAILED, the error `States.Runtime`, and an input shaped like that plane's
  Distributed Map child (`{"BatchInput": {...}, "Items": [...]}`), each of archive, file-ops,
  file-send and table-share sends nothing and logs that nobody could be attributed.
- [ ] No sent text contains the event's `error` or `cause` value.
- [ ] With `inputDetails.included: false`, archive, file-ops and file-send recover the actor through
  `states:DescribeExecution` as their timeout path does. results-conversion, table-builder and
  table-share send nothing and log it.

### FR-004: data-quality and shared-spaces accept the status-change event

#### Description:

Both handlers route an event whose detail-type is `Step Functions Execution Status Change` away
from the ASL path.

- `FAILED` where `is_uncaught_failure(detail)` holds reads the body like this:
  - `detail.input` is a JSON string, so it is decoded with `json.loads`;
  - the result goes through `events.parse_sqs_request`;
  - the actor comes from `cpactor.trusted_actor` on that body.

  The door then sends FR-005's sentence for that plane. Neither plane needs any other field from
  the body, because its sentence is constant and its dedup key is the execution ARN.
- Everything else is a logged no-op.

Neither role gains `states:DescribeExecution`, and an omitted input is a no-op. For that reason these
two doors must **not** call `cpcommon.events.timed_out_execution_input`, which calls
`DescribeExecution` when the input is omitted. On these roles that would be a denied call on every
such event. The ASL path does not change.

#### Acceptance Criteria:

- [ ] Each handler, driven with FAILED and `States.DataLimitExceeded`, and again with
  `States.Runtime`, and an input whose identity block is valid, sends exactly one notification
  whose text equals that plane's FR-005 sentence.
- [ ] Driven with FAILED and the plane's own `Fail` name, with `TIMED_OUT`, or with `ABORTED`, each
  sends nothing.
- [ ] With `inputDetails.included: false`, each sends nothing and logs it.
- [ ] Given a body whose identity block does not verify but whose top-level `actor` or `username`
  names a user, each sends nothing. The body's own assertion is never a recipient.
- [ ] Every existing test of both handlers passes unchanged, including data-quality's `reportKey`
  suppression on the ASL path.

### FR-005: One sentence, with each plane's noun

#### Description:

`cpcommon.messages.uncaught_failure_message(operation, check)` returns the sentence in the
interface contract, in ASCII. Both arguments arrive already rendered. Each plane's `messages`
module exports its pairs as constants, and shared-spaces' module is
`lambdas/shared-space-common/messages.py`.

- **archive** has one pair per mode, and its archive-mode `check` names the request.
  - The machine runs `DeleteSource`, then `WriteReceipt`, then `NotifyArchived`. An error between
    the first two leaves the source deleted and no receipt, and the archive id is the user's only
    route back to their files.
  - So archive mode sends the user to an administrator with the body's `requestId`, as the caught
    `receipt_write_failed` sentence already does.
  - The door fills `{requestId}` from the body. When the body carries none, the `check` reads
    `contact an administrator`.
- **file-ops** has one pair per verb, picked with `focommon.notify.operation_of` exactly as its
  timeout door picks the verb. A copy and a move span two folders, so no single "the folder" is
  right for all three verbs.

| Plane | `operation` | `check` |
|---|---|---|
| archive, archive mode | `archive` | `contact an administrator and quote request {requestId}` |
| archive, restore mode | `restore` | `look at the folder the files would be restored to` |
| file-ops, copy | `copy` | `look at the destination folder` |
| file-ops, move | `move` | `look at both the source and the destination folders` |
| file-ops, delete | `delete` | `look at the folder you were deleting from` |
| file-ops, verb unknown | `file operation` | `look at the folders involved` |
| file-send | `send` | `check with the recipients` |
| results-conversion | `conversion` | `look at the folder you were saving to` |
| table-builder | `table build` | `check the table` |
| table-share | `share` | `contact the Administrator` |
| data-quality | `quality check` | `look for its report in the Data quality tab` |
| shared-spaces | `shared space request` | `check the shared space` |

#### Acceptance Criteria:

- [ ] `uncaught_failure_message("share", "contact the Administrator")` returns exactly:
  "Your share stopped with an internal error before it could report how it went. If you've already
  had a message about it, that message stands. If not, please contact the Administrator before
  trying again."
- [ ] Each row's messages test asserts its full rendered sentence, character for character. That is
  twelve sentences, and archive mode is asserted both with a request id and without one.
- [ ] Driven with an archive-mode FAILED event whose body carries `requestId: "r-1"`, the archive
  door's text contains `quote request r-1`.
- [ ] No rendered sentence begins with the plane resolver's prefix, and every one is ASCII.

### FR-006: The fleet gate holds the door, and the prose says what it is

#### Description:

A fleet test covers every state machine that has a `NotifyFailure` state. The population is derived
from the ASL files and asserted to be eight, as a positive control. The gate holds both halves of
the door, because the rule without its handler is exactly the state Phase 2 and Phase 3 are ordered
to avoid. For each plane, the gate:

- **Rule half.** Asserts FR-002's rule, target and permission.
- **Every pattern.** Inspects every `event_pattern` in the plane's `stepfunction.tf`, not only the
  first.
- **Refuses anything but the two door shapes.** Any pattern whose `detail` is not one of these
  two is refused:
  - `status` exactly `["TIMED_OUT"]` with `stateMachineArn` exactly `[local.state_machine_arn]`;
  - `status` exactly `["FAILED"]` with that same `stateMachineArn` and exactly FR-002's `error`
    list.

  A pattern with no `status` key, or one using `anything-but`, matches FAILED without naming it,
  and is refused like any other.
- **Handler half.** Asserts that the plane's notify-failure module calls
  `cpcommon.events.is_uncaught_failure`. The module is found through an explicit plane-to-handler
  map, because `infra/modules/shared-spaces` pairs with `lambdas/shared-space-notify-failure/`.
  A positive control asserts that every plane in the population maps to a file that exists.

The gate parses Terraform with `lambdas/tf_blocks.py` (`blocks`, `argument`, `map_entries`), the
parser the repo's other `.tf` gates use, and not a new string splitter. Its corpus fixtures are
inline HCL strings. `test_timeout_doors_fleet.py`, `test_state_machine_table_builder.py` and
`test_plane_results_conversion.py` stop taking the first pattern only: they permit FR-002's rule and
still refuse an unfiltered FAILED. The Fences, the register and the prose listed under In Scope
state the filtered exception.

#### Acceptance Criteria:

- [ ] The corpus holds these cases, and each asserts its reason text, not an exit code:
  - (a) a file with FR-002's rule passes;
  - (b) a second rule matching FAILED with no error filter, placed **after** a filtered one, is
    refused with a reason naming the unfiltered pattern;
  - (c) a filter naming only one of the two errors is refused;
  - (d) a filter adding a third name is refused;
  - (e) a file with no FAILED rule is refused;
  - (f) a rule whose target is not the notify-failure function is refused;
  - (g) a pattern with no `status` key is refused;
  - (h) a pattern whose `status` is `[{"anything-but": ["TIMED_OUT"]}]` is refused;
  - (i) a FAILED rule whose `stateMachineArn` is missing or not the machine's own is refused;
  - (j) a plane whose handler module never calls `is_uncaught_failure` is refused.
- [ ] Every check in the gate is mutation-tested once: break it, watch its corpus case fail, restore
  it. The PR names each check and its case.
- [ ] The Fences of `docs/decisions/control-planes.md` and the traps in
  `infra/info/control-plane-shape.md` carry the amended clause.
- [ ] A case-insensitive search for `never[ \`]*FAILED` over `docs/`, `infra/` and `lambdas/`,
  excluding `docs/specs/` and `docs/spec-delivery/`, returns only lines that also state the
  filtered exception. The pattern covers the capitalised `NEVER FAILED` in the `stepfunction.tf`
  comments and the RST double backticks in the handler docstrings. A search for
  `NOT re-checked` in `lambdas/*-notify-failure/` returns nothing.
- [ ] A new entry in `docs/decisions/control-planes.md` records this decision and its rejected
  alternatives. ADR 27's "so the failure mode is silence" in `docs/architecture.md` names the door.

### FR-007: The door is measured in production

#### Description:

After FR-002 deploys, the build runs read-only checks and records the results in
`docs/testing/e2e.md`. What cannot run from a session goes to `docs/testing/owed.md`.

#### Acceptance Criteria:

- [ ] For each of the eight deployed `-failed-uncaught` rules, `aws events test-event-pattern`
  (pattern read with `describe-rule`) is run against five events. It returns `true` for:
  - FAILED with `States.DataLimitExceeded`;
  - FAILED with `States.Runtime`.

  It returns `false` for:
  - FAILED with that plane's `Fail` name;
  - FAILED with `error: null`;
  - TIMED_OUT with `States.Timeout`.

  All 40 results are recorded.
- [ ] For each plane with a FAILED execution in its history, one such execution's
  `describe-execution` reports `error` equal to that plane's `Fail` name. For file-ops, whatever it
  reports is recorded, and it is neither of the two names.
- [ ] One Distributed Map child execution's `stateMachineArn` is recorded, whichever it is. The door
  is safe either way, because FR-003's child-input criterion holds.
- [ ] `docs/testing/owed.md` gains a row for the first real uncaught failure in production. It
  passes when the user's notification arrives with FR-005's sentence.

---

## API / Interface Contract

```python
# lambdas/control-plane-common/cpcommon/events.py
UNCAUGHT_ERRORS: frozenset[str] = frozenset({"States.DataLimitExceeded", "States.Runtime"})

def is_uncaught_failure(detail: Any) -> bool:
    """True for a FAILED status-change detail whose error is one no Catch in the fleet takes.

    Never raises. A detail that is not a dict, a status that is not the string "FAILED", and an
    error that is not a string (a list or dict would raise TypeError out of a bare `in`) all
    return False. The error is tested with `events.in_vocabulary(error, UNCAUGHT_ERRORS)`. A
    raise here would be an async Lambda failure, which EventBridge retries.
    """

# lambdas/control-plane-common/cpcommon/messages.py
def uncaught_failure_message(operation: str, check: str) -> str:
    """The sentence for a run that ended on an error no Catch takes."""

uncaught_failure_message("share", "contact the Administrator")
# "Your share stopped with an internal error before it could report how it went. If you've
#  already had a message about it, that message stands. If not, please contact the
#  Administrator before trying again."
```

```hcl
# infra/modules/<plane>/stepfunction.tf
resource "aws_cloudwatch_event_rule" "execution_failed_uncaught" {
  name = "${local.state_machine_name}-failed-uncaught"
  event_pattern = jsonencode({
    "source"      = ["aws.states"]
    "detail-type" = ["Step Functions Execution Status Change"]
    "detail" = {
      status          = ["FAILED"]
      stateMachineArn = [local.state_machine_arn]
      error           = ["States.DataLimitExceeded", "States.Runtime"]
    }
  })
}
```

## File & Folder Structure

```
infra/modules/base/policies/github-actions-deploy-<plane>.json.tftpl   # FR-001 (x7)
infra/modules/<plane>/stepfunction.tf                # FR-002: rule, target, permission (x8)
lambdas/control-plane-common/cpcommon/events.py      # UNCAUGHT_ERRORS, is_uncaught_failure
lambdas/control-plane-common/cpcommon/messages.py    # uncaught_failure_message
lambdas/<plane>-common/<prefix>common/messages.py    # each plane's operation and check (x7)
lambdas/shared-space-common/messages.py              # shared-spaces' pair (no package dir)
lambdas/<plane>-notify-failure/<prefix>_notify_failure.py   # FR-003 / FR-004 routing (x8)
lambdas/info/deployment.md                           # the rollback floor
lambdas/test_failed_doors_fleet.py                   # FR-006 gate and its corpus
lambdas/test_timeout_doors_fleet.py                  # reads every event_pattern
```

## Implementation Phases

### Phase 1: The deploy role (FR-001)

- Add the `-failed-uncaught` rule ARN to seven planes' `events:` statements. data-quality gets its
  statement new. Read `infra/info/deploy-role-iam.md` first.
- Its own PR. Merge it, and watch Deploy Infrastructure go green on `main`.

### Phase 2: The sentence and every door (FR-005, FR-003, FR-004)

- `UNCAUGHT_ERRORS`, `is_uncaught_failure` and `uncaught_failure_message` in `cpcommon`, with each
  plane's pair.
- Status routing in the six timeout doors, and the new door in data-quality and shared-spaces.
- One PR. It is inert, because no rule sends a FAILED event yet. Watch Deploy Lambdas go green.

### Phase 3: The rules, the gate and the prose (FR-002, FR-006)

- The rule, target and permission on eight planes.
- The fleet gate and its corpus, and the first-pattern tests changed to read every pattern.
- The Fences, the register entry, ADR 27, and the docstring, README and comment sweep, closed with
  a grep.
- One PR. This is where the door goes live.

### Phase 4: The measurement (FR-007)

- The 40 pattern results, the caught-failure `error` names, and the child's `stateMachineArn`, into
  `docs/testing/e2e.md`. The owed row goes into `docs/testing/owed.md`.
