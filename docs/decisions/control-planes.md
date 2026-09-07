# Control planes — one pattern, eight planes, and the traps are shared

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries a table pointing at each area's Fences. This file opens with those fences — the traps that
apply green and fail later — and holds the reasoning, the constraints and the explicit "do NOT
build" fences for one area beneath them. **Read the Fences before working in the area, then the
entry you need, not the file.**

## Contents

- [Fences](#fences)
- [Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)](#everything-unbounded-on-the-state-travels-by-pointer--including-the-definition-spec-161-extending-spec-090160)
- [Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)](#every-control-plane-machine-that-can-run-for-hours-declares-a-timeoutseconds-spec-161)
- [Data-quality outcome notifications (SPEC-114)](#data-quality-outcome-notifications-spec-114)
- [Control-plane DLQ drain → user notification (SPEC-126)](#control-plane-dlq-drain--user-notification-spec-126)
- [Structured-logging pipe (SPEC-127→129)](#structured-logging-pipe-spec-127129)
- [Structured-logging narrative primitives & the one-door rule (SPEC-130/131)](#structured-logging-narrative-primitives--the-one-door-rule-spec-130131)
- [The field rule — what may be logged (SPEC-130)](#the-field-rule--what-may-be-logged-spec-130)
- [Per-plane instrumentation rules (SPEC-132→137)](#per-plane-instrumentation-rules-spec-132137)
- [No ASL state decodes an error Cause (PR #252, control-plane-wide)](#no-asl-state-decodes-an-error-cause-pr-252-control-plane-wide)
- [Notifications (SPEC-058→061)](#notifications-spec-058061)
- [Every plane notifies on a pre-verb failure, and `failure_reason` is the only decoder (SPEC-152)](#every-plane-notifies-on-a-pre-verb-failure-and-failure_reason-is-the-only-decoder-spec-152)
- [A layer gate must check the copy list, not the flag map (SPEC-153)](#a-layer-gate-must-check-the-copy-list-not-the-flag-map-spec-153)
- [The deliberate twins are discharged: one implementation per cross-plane helper (SPEC-156)](#the-deliberate-twins-are-discharged-one-implementation-per-cross-plane-helper-spec-156)
- [The copy is a top-level Distributed Map, and attribution is a verb (SPEC-160)](#the-copy-is-a-top-level-distributed-map-and-attribution-is-a-verb-spec-160)
- [A post-identity failure needs its own seed, and the fleet guard cannot see it (SPEC-165)](#a-post-identity-failure-needs-its-own-seed-and-the-fleet-guard-cannot-see-it-spec-165)
- [The machine's ceiling cannot notify on its own, and this plane's timeout door needs a fallback (SPEC-166)](#the-machines-ceiling-cannot-notify-on-its-own-and-this-planes-timeout-door-needs-a-fallback-spec-166)
- [The lock protocol is `cpcommon`'s, extracted ahead of its second consumer (SPEC-187)](#the-lock-protocol-is-cpcommons-extracted-ahead-of-its-second-consumer-spec-187)
- [The engine's attribution vocabulary belongs to the CALLER, not to cpcommon (SPEC-189)](#the-engines-attribution-vocabulary-belongs-to-the-caller-not-to-cpcommon-spec-189)
- [Two budgets, and both were wrong before they were computed (SPEC-189)](#two-budgets-and-both-were-wrong-before-they-were-computed-spec-189)
- [One producer, after the release, reached from BOTH of ReleaseLock's edges (SPEC-191)](#one-producer-after-the-release-reached-from-both-of-releaselocks-edges-spec-191)
- [A notification payload is bounded by BYTES, and the binding case is the PLAIN one (SPEC-191)](#a-notification-payload-is-bounded-by-bytes-and-the-binding-case-is-the-plain-one-spec-191)
- [The run's ONE sentence opens neutrally, because its residue is not all failure (SPEC-191)](#the-runs-one-sentence-opens-neutrally-because-its-residue-is-not-all-failure-spec-191)
- [A resolved space carries its own IDENTITY, not only its location (SPEC-191)](#a-resolved-space-carries-its-own-identity-not-only-its-location-spec-191)
- [`requestId` rides on every row, including a clean run's and a failed run's (SPEC-191)](#requestid-rides-on-every-row-including-a-clean-runs-and-a-failed-runs-spec-191)
- [The outcome link: destination, source, or the common folder of the items' PARENTS (SPEC-191)](#the-outcome-link-destination-source-or-the-common-folder-of-the-items-parents-spec-191)
- [The outcome wording reuses the failure bodies and is deliberately NOT a resolver (SPEC-191)](#the-outcome-wording-reuses-the-failure-bodies-and-is-deliberately-not-a-resolver-spec-191)
- [A pre-existing notifications spoofing gap, recorded and not fixed here (SPEC-191)](#a-pre-existing-notifications-spoofing-gap-recorded-and-not-fixed-here-spec-191)
- [The notifications `create` boundary is a runtime check, because IAM cannot express it (SPEC-206)](#the-notifications-create-boundary-is-a-runtime-check-because-iam-cannot-express-it-spec-206)
- [A delete removes people, not things — and retention keys on a durable fact, never live status (SPEC-205)](#a-delete-removes-people-not-things--and-retention-keys-on-a-durable-fact-never-live-status-spec-205)
- [One predicate decides who may be destroyed and who may be added (SPEC-205)](#one-predicate-decides-who-may-be-destroyed-and-who-may-be-added-spec-205)
- [The emptied record is inert because the `owner` FIELD is cleared (SPEC-205)](#the-emptied-record-is-inert-because-the-owner-field-is-cleared-spec-205)
- [A control-plane queue may have a second producer, admitted by SenderId (SPEC-208)](#a-control-plane-queue-may-have-a-second-producer-admitted-by-senderid-spec-208)
- [A transfer's refusals are RETURN VALUES, because a raise in the validator reaches nobody (SPEC-208)](#a-transfers-refusals-are-return-values-because-a-raise-in-the-validator-reaches-nobody-spec-208)
- [A single-verb write pipeline is a queue and a writer, and its DLQ is undrained for a reason of its own (SPEC-211)](#a-single-verb-write-pipeline-is-a-queue-and-a-writer-and-its-dlq-is-undrained-for-a-reason-of-its-own-spec-211)
- [The operator door widens to member management, and that is a threat-model decision (SPEC-217)](#the-operator-door-widens-to-member-management-and-that-is-a-threat-model-decision-spec-217)
- [A conversion reads the RESULT, never the source, and ownership is a question about a path (SPEC-221)](#a-conversion-reads-the-result-never-the-source-and-ownership-is-a-question-about-a-path-spec-221)
- [The converter's shape is decided by what cannot stream and what cannot be retried (SPEC-222)](#the-converters-shape-is-decided-by-what-cannot-stream-and-what-cannot-be-retried-spec-222)
- [A closed vocabulary is type-checked before it is looked up (PR #662, control-plane-wide)](#a-closed-vocabulary-is-type-checked-before-it-is-looked-up-pr-662-control-plane-wide)

## Fences

Shared spaces, table builder, table share, data quality, file send, **archive**, file
operations and results conversion each get:
a **FIFO SQS** queue → EventBridge Pipe → Step Functions → single-task verb Lambdas, **one execution
role per plane** and its own DLQ; `cpcommon` and a domain module are a CODE split, not a packaging
one, since the cutover. A plane sharing another's
DLQ lets one malformed request dead-letter someone else's work.

**The traps, every one of which ships green:**

- **No ASL state may decode an error `Cause`.** `States.StringToJson($.error.Cause)` raises
  `States.Runtime`, which is **uncatchable anywhere**. Carry raw `$.error`; decode with
  `cpcommon.errors.failure_reason`, the only decoder.
- **Every plane notifies on a pre-verb failure** — a `NotifyFailure` before `Fail`, reached on every
  path, because the no-verb-ran paths cannot be selected for in ASL.
- **A post-identity failure needs its own seed.** A catch routed to a state reading `$.raw` raises an
  uncatchable error *before* the notifier, because `$.raw` exists on no post-validate state.
- **Everything unbounded travels by pointer**, never on the state, and **a cap is not a substitute**.
- **Every cap is COMPUTED by a test**, against the budget that sized it — memory, makespan, or a
  service quota — and it names that budget. A hard-coded number hides a wrong model.
- **`TimeoutSeconds` is TOP-LEVEL and cannot notify on its own**: catchers do not cover top-level
  execution failures, so a ceiling ships **with** an EventBridge `TIMED_OUT` rule (never `FAILED`, or
  every caught failure double-notifies).
- **An expected refusal is a RETURN VALUE** — a raise in a validator reaches nobody, and a
  `TerminalError` cannot name the item. Collapse what a REQUESTER reads, or it is an oracle.
- **ONE producer says every per-recipient outcome**, at the end of the machine — not each verb.
- **Locks are objects claimed under ETag CAS**, released by **overwriting**: with `DeleteObject`
  denied, "free" is a state rather than an absence. The holder is the **execution ARN**, because a
  request id identifies the message and Pipes delivery is at-least-once.
- **A partial teardown never frees the name.** `delete_objects` returns **HTTP 200 with a per-item
  `Errors` array**, so a partial failure reads as success; raise, and leave the registry record —
  the record *is* the name lock.
- **A shared-space delete removes PEOPLE, not things**, keyed on the durable `everActive` — never
  live `status`, which moves `active → deleting → failed` over intact data, and where `deleting` is
  **not** evidence a space was usable (delete is gated on ownership alone). **One predicate**,
  `is_destroyable`, routes the delete AND refuses the add; complements written twice drift silently
  both ways. Inert because the `owner` **field** is cleared, or for the member actions `emptiedAt` — so
  test it **as the original owner** AND on a live record.
  A name is never reusable.
- **The planes do not verify — they read the API's `identity` block**, whose writers are
  enumerated: the API, and one reader by `SenderId`. Dropping a verification is NOT dropping an authorization:
  `authorize`/`authorize_source` have **zero diff**. `cpcommon.actor` **cannot verify** (no `jwt`,
  `auth`, network or env — import sweep), and the flat `actor` is **never** read: it carried a raw
  JWT, and a JWT and a username are both non-empty, so the guard is the **shape rule**.
  `assurance` fails closed on an unknown value **including an absent one**. Do **NOT** add a queue resource policy — a blanket
  `Deny` there silences EVERY notifying role in the fleet, invisibly, and the fleet grows. A pre-cutover message is `unauthorized` and
  does **not** dead-letter (`FIRE_AND_FORGET`), so plane allowed-field sets stay untightened.
- **The DLQ drain** sweeps request DLQs and notifies from **`identity.actor`**; its redaction
  blanks the two LEGACY token fields, since a stale message still carries one. Two are undrained:
  notifications (circular), feedback (no identity in its body).
- **File operations are synchronous IFF exactly one file**; the lock is per **space** and its loser
  **waits** (cross-space takes both in digest order or neither); the **space root is refused** as an
  item; the collision unit is the derived destination **key**, and a **403 counts as occupied**; the
  deletion takes **confirmed plan keys** — a prefix listing orphans an uncopied object.
- **The browser's async switchover consults the routing predicate ONCE**, above every submission
  point, in one dispatcher. The in-flight record is **session-scoped, never persisted**, and settles
  on a notification carrying its request id.
- **Table share CLONES the source definition, never re-infers it**, and pushes without consent.
- **A data-quality notification IS the completion channel** and must carry the report link, because
  the reports folder is hidden. Its runs index is appended under **ETag CAS** — S3 lists
  lexicographically, so a UUID key gives no chronology.
- **Every member sees the roster**; the join acknowledgement is display-only, since access is granted
  at add time.
- **The notifications `create` boundary is a RUNTIME check**, because no SQS condition key reaches a
  message body. It compares the **role-id half** of the `SenderId`, and a refusal **logs and drops,
  never raises** — dead-lettering per forged request would drown its undrained DLQ. The actor
  reader replaces the `USER_ACTIONS` arm **only**: `create` is the trusted producer (body username,
  no actor, no token), and hoisting the reader above that branch refuses **every notification the
  fleet produces**, silently.
- **`cpcommon` owns the algorithm; a domain layer owns its wording.** Do **NOT** merge the domain
  layers wholesale.
- **A closed vocabulary is TYPE-CHECKED before it is looked up** — `cpcommon.events.in_vocabulary`,
  never a bare `value not in VOCAB`. `in` **hashes its left operand**, so a request field holding a
  list or a dict raises `TypeError` out of the membership test itself, before the plane can raise
  its named refusal, and `notifies_on_failure` records that instead of a reason code. It is a
  **predicate, not a raise**, because the wording is the domain's; it is a `TypeGuard[str]`, so a
  caller that refuses on False keeps its narrowing. Its vocabulary is typed as a **set or mapping,
  never `Container`** — `in` on a `str` is a SUBSTRING test, so a string vocabulary would admit
  every infix of itself. A **positive-form** test (`x if x in V else …`)
  hashes exactly the same, and one hid in each of the two mode readers that pick a plane's wording
  (`_wording_mode`, `_mode_from_raw_request`) — including
  the notifier of last resort, documented as raising nothing.
- **A conversion reads from the ACTOR'S space and writes to the DESTINATION'S**, and the two
  coincide only for a personal destination — which is why a suite whose fixtures are all personal
  cannot tell them apart, and why one shipped reading the result object out of the shared bucket.
  Its **types come from the metadata**, where a decimal's parameters are **never in `Type`** —
  captured — and are read from `Precision`/`Scale`, which no capture route available here can
  show are populated; the verb refuses the column rather than guessing a scale, so being wrong
  about that costs a loud refusal and not a silently rounded number. The vocabulary is closed and
  **refuses rather than falling back**. Excel is
  the one format that cannot stream, so its size cap is set by MEMORY at a measured 23–32x the
  CSV while the others are set by the disk — one cap for all three either starves Parquet or
  promises an Excel conversion that OOMs. `Convert` retries **`TransientError` only**: a `Lambda.*`
  retry can re-run an invocation that already completed its conditional `PutObject`, and it then
  meets its own object and reports `destination_occupied` for a save that succeeded.
- **A conversion's destination prefix is RELATIVE to the space root; the browser's picker is
  absolute.** Passing one through writes `alice/alice/…` and **nothing refuses it** — containment
  only proves the key starts with the root, which a doubled root does. Derive the root from the
  string being sliced: a lookup needs a fallback, and the only one available is the bug.
- **A refusal that cannot fire is a fence that misleads everyone downstream.** Excel's
  16,384-column ceiling is unreachable here — the described columns ride the 256 KB state, which
  a realistic column entry fills between ~2,500 and ~6,400 — so the cap that exists is the
  TRANSPORT's, sits in describe-results, and applies to every format.
- **A conversion's input is the EXECUTION'S RESULT OBJECT, never the source table**, and an
  execution is the actor's **iff Athena wrote it under `cpcommon.results.user_results_prefix`** —
  the one builder the API starts every query with, so a guessed id names nothing the actor cannot
  already read. A plane refusing protected destinations mirrors its role's **any-depth** Deny
  rather than the browser's root-anchored picker: an IAM wildcard matches `/`, so a validator
  anchored at the root accepts a key IAM then refuses at the write.
- **A notification's optional `link` is gated by `isSafeInAppPath`**, and a route that renders one
  must not become an existence oracle: the data-quality report view takes its space **from the route,
  never derived**, and an unreachable space renders denied while issuing **no S3 request at all**.
- **Structured logging** goes through `cpcommon.observability` only; the logs queue is FIFO, swept on
  a schedule, appended under ETag CAS, retained forever. `@traced` outermost — **except the API**, where one decorator sits
  outside it to turn an unpredicted fault into a declared code: a catch INSIDE the span ends every
  failed request successfully and the fault is recorded nowhere. Messages are literals.
  The **`error.stack` exemption covers file contents, NOT credentials**, and it covers **no field a
  call site chooses to emit** — neither a **SQL statement** nor an Athena **`stateChangeReason`** may
  be one, since both quote a user's own cell values back; `sql_bytes` and `state` instead. The API
  **prevents rather than redacts**: there is no scrubber, a handler is never given a credential, and
  an AST sweep is what holds it.

## Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)

The rule the table-share plane arrived at over three specs, stated once: **anything on the Step Functions state whose size a user controls lives in the admin bucket and rides as a key.** The object list went first (PR #256, at 95% of the 256 KB payload), the transfer manifest was born that way (SPEC-160), and SPEC-161 finishes it with the **cloned table definition** — `{admin_bucket}/table-share/{hash}/definition.json`, written by `inspect-source`, fetched by `create-table`. `tscommon.copy_plan` owns all three key layouts, so the request digest has one home.

**A cap is not an alternative to a pointer, and this is the case that shows why.** The definition was bounded inline by `SHARE_MAX_DEFINITION_BYTES` at 32 KiB, and that number was doing two incompatible jobs: keeping the Map's state safe, and deciding how wide a table a user may share. A 100-column table with column comments serialises to roughly 32 KiB — an ordinary thing to want to share, sitting exactly on the boundary. Measured: with the definition inline at cap, the guard Map's peak state reaches **~55%** of the limit; with the pointer it is ~29%. The cap could protect the payload or serve the user, not both. **`test_the_whole_map_state_stays_under_the_payload_limit` now adds an at-cap definition back to the modelled state and asserts it fails the safety bar**, so the pointer is demonstrated to be load-bearing rather than assumed to be tidy.

`SHARE_MAX_DEFINITION_BYTES` survives at **64 KiB** as an object-size sanity check, and **what sizes it is now Athena, not Step Functions**: the definition renders into one `CREATE EXTERNAL TABLE`, and Athena's query-string quota is **262,144 bytes and not adjustable**. The rendered statement can be **twice** the serialised JSON — `ddl.literal` backslash-escapes, so a `'` costs one byte in the JSON and two in the DDL — and *where* those quotes sit decides the ratio: a table property or SerDe parameter carries ~9 bytes of JSON overhead and renders at nearly the full 2x, where a column comment carries ~40 and reaches only ~1.7x. At 128 KiB the property-shaped worst case measured **99.98%** of the quota; at 64 KiB it is 50%. Do not re-read it as a state bound, and do not raise it on the strength of a comment-shaped measurement.

**Three keys, two disciplines, and the split is about what the content depends on.** The plan and the definition are **pure functions of the request** — the digest covers the source database and table, so two overlapping executions write byte-identical content and either object is correct for either run. The manifest is **execution-unique**, because its lines depend on which recipients the guard Map accepted, which is time- and destination-dependent (SPEC-160's entry has the full argument). Do not "make them consistent" by giving the definition an execution segment; it would multiply objects under a lifecycle rule for no gain.

**An unreadable definition fails THAT RECIPIENT, never the request, and never renders anyway.** `definition_unreadable` is terminal for the finish Map's item, and the reason the load refuses an object with no columns rather than passing it on is specific: an empty column list renders a `CREATE EXTERNAL TABLE` that **Athena accepts**, over the recipient's freshly-copied data — a table that reports success and returns nothing.

**No IAM changed.** `CopyPlanReadWrite` already grants `PutObject`/`GetObject` on `${admin_bucket_arn}/table-share/*`, which is the whole benefit of one prefix owning every artifact — and the same property is why FR-004 was discharged by adding **no lifecycle rule**. Detail: `spec-delivery/SPEC-161`.

## Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)

A Standard workflow with no `TimeoutSeconds` runs to Step Functions' default of **one year**. That was harmless while the copy was one Lambda bounded by its own 900-second timeout; once SPEC-160 made it a Distributed Map and SPEC-161 raised the byte cap to 1 TiB, "wedged" became a state a run could sit in indefinitely.

**It is a TOP-LEVEL ASL field** — beside `StartAt`, not an argument to `aws_sfn_state_machine` and not a task field (SPEC-157 settled the same distinction for the table-builder's lock). On a Task it would bound one step, which is not what a wedged *run* needs.

**And a top-level timeout CANNOT reach `NotifyFailure`, which is the trap this entry exists to record.** The state sits in the machine looking exactly like it would. It does not: AWS documents that *"Step Functions catchers are available for Task, Parallel and Map states, but not for top-level state machine execution failures"*, and the remedy it names is *"listen for `TIMED_OUT` events from Standard workflows with an EventBridge bus"*. A top-level expiry terminates the execution outright — no state runs, no `Catch` fires. **A `TimeoutSeconds` shipped alone would therefore have bounded the run and made the sender's silence permanent instead of merely long**, which is worse than it sounds: SPEC-152's guarantee would read as satisfied by a state that could never be reached.

So the field ships **with an EventBridge rule** (`stepfunction.tf`) on `Step Functions Execution Status Change`, matching **`TIMED_OUT` only** and invoking the same `notify-failure` verb through a second door. AWS classifies Step Functions execution events as **best-effort delivery**, so this closes the hole rather than sealing it — a dropped event means the old silence for that one run. That is accepted: the alternative is polling `ListExecutions`, which is a scheduled sweep and a second moving part for a failure mode measured in runs per year. `TIMED_OUT` only is load-bearing: every other whole-request failure already reaches the verb through a `Catch` and ends at `Fail`, whose status is `FAILED`, so matching both would send a second notification for every caught failure. The two doors are disjoint by construction, not by a suppression rule.

**The timeout door recovers the sender from the token, and expiry is deliberately not enforced.** The execution input is what the Pipe forwarded — the raw SQS batch — so the actor is the verified `cognito:username` claim inside the body's ID token, never the body's own assertion. By construction that token is expired: the timeout fires hours after it was minted. The relaxation is the DLQ drain's, taken through the same separately-named entry point (`verified_username_ignoring_expiry`) and safe for the same reason — this path **grants nothing**, it only addresses a message. An input EventBridge omitted (it caps an event at 256 KB) or a token that will not verify is a **logged no-op**, never a guessed inbox. Its wording is its own reason code, `share_timed_out`, rather than the generic failure sentence: a timeout is the one whole-request failure that can leave a recipient holding **part** of a dataset — the copy may have run and the create may not — so "try again" alone would be wrong advice.

> **Superseded in part by SPEC-201 (2026-08-30):** the token half only. The door recovers the sender
> from the message's `identity` block, so "by construction that token is expired" describes nothing —
> there is no token, the API verified the bearer at the edge, and the `*_ignoring_expiry` entry point
> this cited is deleted. Everything else here stands unchanged, including the degradation: an input
> EventBridge omitted, or a block that will not read, is still a **logged no-op and never a guessed
> inbox**, and the reason code is still `share_timed_out`. There are **four** such doors, not three —
> Arc A's file-ops plane added one.

**Sized from `SHARE_MAX_TRANSFER_BYTES`, NOT from the source cap — and the difference is a factor of `SHARE_MAX_RECIPIENTS`.** The manifest carries one item per (recipient, object) pair and every item is a full copy, so the Map moves the source **once per recipient**. Sized against the 1 TiB source cap alone, this number was short by 50×: 50 recipients × 1 TiB is 50 TiB, which needs 3.8 hours even at the conservative rate. That is the omission `SHARE_MAX_TRANSFER_BYTES` (3 TiB) closes. **And the rate it is divided by is a makespan, not an aggregate bandwidth** — a fourth review round's correction, and the same class of error a fourth time: `copy_batch` gives one whole object to one worker and `copy_one` part-copies serially, so a batch dominated by one large object runs at ONE stream while seven idle. The pessimistic denominator is `MAP_MAX_CONCURRENCY × rate` (500 MB/s), not `× COPY_CONCURRENCY ×` it (4 GB/s) — under which 16 TiB read as 4,400 s when the truth was 35,000. At 500 MB/s, 3 TiB is ~6,600 s, and with the finish Map (3,000 s) and the serial verbs (~720 s) the worst run is ~10,300 s inside **10,800 s (3 h)**. The margin is bought against the sender's silence, so a longer timeout is a slower failure signal rather than free safety; the cap moves before the timeout does. **A test computes it**, because the hard-coded floor that stood here first is exactly what let the mismatch survive two review rounds.

**The retention obligation inverts once a run can last hours.** Nothing new needed expiring: manifest, definition and Map Run export all sit under `table-share/`, which `expire-table-share-copy-plans` already covers. The risk was the opposite — the rule expiring a *live* run's manifest underneath it. `admin_results_retention_days` (30) clears the run ceiling by **240×**, computed by a test from both files, and **no rule and no rule id were added**.

## Data-quality outcome notifications (SPEC-114)

The notification **is** the completion channel — the browser never waits and the reports folder is hidden from the file browser, so a success message without a **link to `/data-quality/{space}/{requestId}`** would leave the report unreachable. The link builder mirrors SPEC-113's resolution precedence and returns **nothing** where the view would resolve the wrong space (a shared space named like the actor, a personal space that isn't theirs) — no link beats a permanent not-found. **Every figure this arc produces is approximate**, so a flat "some figures are estimates" rides every success message and the real warning is reserved for `hasIncompleteFigures`, the flag that varies. Failure covers three layers: `@notifies_on_failure` on every verb, the `NotifyFailure` state for what no verb can catch (import/SFN-level errors, decoded in Python — never in ASL), and **SPEC-126** for what never starts an execution at all. **One dedup token per outcome, not per verb** (`{requestId}:failure` / `:completed`): `NotifyFailure` runs after the execution has left the failing verb and cannot know which one raised, so a per-verb token would send two messages for one failure; the collapse relies on SQS FIFO's 5-minute window. `TerminalError` gained an optional **`tokens`** mapping — the user-facing inverse of `detail`, which stays raw and operator-only. **FR-005's CloudWatch alarms were removed, not deferred** (user decision): an alarm with no target, on one arc of five, told the user nothing. Detail: `spec-delivery/SPEC-114`.

## Control-plane DLQ drain → user notification (SPEC-126)

Replaces SPEC-114 FR-005. Every control plane dead-letters a request it cannot process, and until this shipped the user was told **nothing at all** — no verb ran, so no `@notifies_on_failure` fired; no execution started, so no `NotifyFailure` state was reached. **One shared drain Lambda** (`lambdas/control-plane-dlq-drain/`, `infra/modules/control-plane-dlq-drain/`) sits on all four request DLQs (data-quality, table-builder, table-share, shared-spaces) and turns each dead-lettered message into one notification. Four things are load-bearing: (1) the recipient is the **verified `cognito:username` from the token inside the body** — a body-asserted `username` would let anyone route a notification to anyone; (2) **expiry is not enforced** on this path (`cpcommon.auth.verified_username_ignoring_expiry`, a **separately named** entry point, never a flag on the function every authorization path calls) because a dead-lettered message is old by construction while an ID token lives an hour — signature/issuer/audience still are, and this path **grants nothing**; (3) **no value from the untrusted body reaches the message** — every other producer interpolates what a verb already authorized, nothing here has authorized anything, and echoing an attacker-supplied path into a victim's inbox would make notifications a text-injection channel; (4) every per-message path is **total** — a throw means redelivery, and a message that always throws loops until retention expires, burning invocations on a failure nobody is watching, which is the invisibility this exists to end. The dead-lettered body is logged (**token redacted**) before the drain consumes it, trading the DLQ's 14-day copy for the log group's.

> **Superseded in part by SPEC-201 (2026-08-30):** points (1) and (2). The recipient is the
> `identity.actor` the API stamped, trusted because SPEC-200 FR-008 made the API the only principal
> that may write these queues — provenance rather than cryptography. So (2) is void: there is no
> expiry to relax and no `*_ignoring_expiry` entry point left, and the per-source `token_field`
> column is gone rather than set to one value on every row. The redaction did **not** go with it:
> it now blanks the two LEGACY top-level token fields, because a message enqueued before the flip
> still carries one and is exactly what this drain surfaces. It must not be pointed at `identity` —
> top-level replacement would blank the block the recipient was just read from. Points (3) and (4),
> and the undrained notifications DLQ, are unchanged.

The **notifications DLQ is deliberately undrained** and is the one hole this cannot close — the drain's only delivery channel is the queue that DLQ implies is broken; the honest answer there is operator-facing. **No redrive, no replay, no CloudWatch alarms** (an alarm with no target told the user nothing — the user decision that killed SPEC-114 FR-005). **Follow-up (2026-07-22): the four SQS event-source mappings became one EventBridge scheduled sweep** (`rate(10 minutes)`) — the mappings idle-long-polled four almost-always-empty DLQs around the clock, and that was the bulk of the account's SQS request volume (it was tripping the 1M/month free tier). The handler now polls all four DLQs itself (`DLQ_ARNS`, the same ARNs as an env JSON list) and **deletes every message it reads whether or not it could notify**, so "total by construction" now means *never redeliver* rather than *safe to be redelivered* — the redelivery-loop hazard in (4) is moot because nothing redelivers (the `_guarded_notify` belt stays, so one bad message can't abort the sweep). A resource-based `lambda:AddPermission` lets the rule invoke the function, so **no invoke role** is needed (unlike EventBridge Scheduler); the execution role is unchanged (it already held the four DLQ read/delete grants the mappings polled with). Cost fell from ~10⁵–10⁶ idle receives/month to a few thousand; the price is that a dead-lettered request surfaces within one interval (~10 min) rather than seconds, immaterial for a queue nothing watches live. Detail: `spec-delivery/SPEC-126`.

## Structured-logging pipe (SPEC-127→129)

The pipe every control-plane function logs through; it carried **boundaries only** until SPEC-130 added the narrative half (next entry). `log-foundry` (pinned **exactly**, core not `[aws]`) ships in the `cpcommon` layer. `LOGS_QUEUE_URL` is **optional** (`environ.get`, never `_require`) so a function missing it logs to stdout instead of crashing a whole plane at cold start. The logs queue is **FIFO** with `message_group_id` = the **service** (SPEC-129; it was standard only until `log-foundry` 0.5.0 could set `MessageGroupId`), with **no** content-based dedup (the library mints UUID dedup ids), and it is **swept** on a 10-min schedule, never long-polled (#270/#271). `service` = the **control plane**, and it is untrusted input on an S3 key: anything failing `^[a-z][a-z0-9-]{2,62}$` goes to `logs/_unrouted/`. Layout is `logs/service={s}/year=/month=/day=/data.jsonl` — **one appended object per service-day**, so every write is an **ETag-CAS read-modify-write** (a failed read must never overwrite a day) and the sweep role can **read** `logs/*`, reversing SPEC-127 FR-006. Delivery is put-then-delete (at-least-once; duplicates collapse on `log_id`). Partitions come from the **event's** timestamp. `logs/` is retained **forever**. `@traced` goes **outermost, above `@notifies_on_failure`**, or failed invocations close their span as `ok`. One run = **nine traces**, joined on `fields.request_id`.

## Structured-logging narrative primitives & the one-door rule (SPEC-130/131)

The pipe SPEC-127/128/129 built carries **boundaries only** (entry above), and SPEC-130 opens the door to the narrative half. `cpcommon.observability` gains `info`/`warning`/`error` and `step(name)` — the module's full surface is `init`/`flush`/`traced`/`step`/`stamp`/`info`/`warning`/`error` — and **nothing outside that module may import `log_foundry`**: an emitter sits in the middle of business logic where an exception is a real failure path, so the never-raise discipline needs one door rather than thirty-four. `step` is a **thin** alias for `lf.trace` and must stay one: the library decorator is non-swallowing, and `@traced` sits **outermost above `@notifies_on_failure`**, so a step that caught anything would cost the user their failure notification. Messages are **literals**, everything variable is a field (an f-string message mints a distinct string per run and can be neither counted nor filtered). The narrative **never reaches the console**: `echo=` is prohibited repo-wide and grep-tested, dropped-and-warned when passed as a field (with `**fields` it is otherwise a silent no-op emitting a field named `echo`); the one named exposure is `init`'s `StdoutSink` fallback when `LOGS_QUEUE_URL` is unset, which **stays** because it is the cold-start safety property the module is shaped around (PR #196) and is bounded by the `logging.getLogger()` calls already putting the same keys in the same log group.

Two identity defects fixed at the same time, because instrumenting on top of them would have multiplied the damage: `traced` now passes **`name=verb`** (without it `log-foundry` falls back to `fn.__qualname__` and every root span in the fleet read `function: "handler"`) — a **discontinuity in a store retained forever, accepted without migration** since rewriting appended NDJSON would risk a day of logs to save a `WHERE` clause, with `fields.verb` populated on both sides so a query spans the cutover; and **`verb` moved from a span default to baggage** (set after `_reset_baggage`, which clears the whole mapping), because a span default reaches that span's own events and nothing nested — the first `step` child would have carried `request_id` but not the verb that produced it. Consumers: SPEC-131 (sweep), 132 (data-quality), 133 (DLQ drain), 134→137 (the rest of the fleet).

**SPEC-131 added an eighth name, `stamp(**fields)`** (trace baggage), because the sweep needed an invocation-scoped join key on the boundary spans and the only alternative was importing `log_foundry` at a call site — the one-door rule survives by widening the door, not by excepting it; `_stamp_verb` and `_stamp_request_id` now delegate to it. **SPEC-131's own bound is structural:** the sweep emits into the queue it drains, so its event count is O(1) in messages and O(G) in day-groups (measured `6+4G`, 4 on an empty sweep) — a per-message emitter would give that queue a floor it could never get below, and the guard is a test that sweeps 20 then 200 messages over the same groups and demands an identical count. Its CloudWatch calls **stay alongside** the events, uniquely for that function: the sink is SQS-only, so a sweep that cannot write to S3 cannot report through the structured store that it could not write to S3. Detail: `spec-delivery/SPEC-130`, `spec-delivery/SPEC-131`.

## The field rule — what may be logged (SPEC-130)

**The line is drawn at file contents — not at user-derived data** (user decision, 2026-07-23): `logs/` lives in the admin bucket and is read by administrators, and that destination is what makes user-derived *metadata* the right thing to log — file names, S3 keys, prefixes, **usernames** (already the S3 prefix, the principal tag and the Glue DB name, SPEC-033), database/table/**column names**, space names, counts and durations are all permitted and encouraged, because an operator debugging a failed run needs to reach the object. **Absolutely never: data from inside a file** — a cell value, a sampled row, a result set, a decoded byte range — because it can be PII, it is never needed to debug a control plane, and `logs/` is retained forever (column *names* are schema and are in; column *values* are contents and are out). **Never regardless of provenance: tokens, credentials, email addresses** — a bearer credential is not metadata, and an email is the only personal contact detail that would exist in a forever-retained prefix. There is deliberately **no runtime redaction filter** and the module docstring says so: the rule turns on *provenance*, which no filter over a field name or value shape can see, and a filter that looked like enforcement would be worse than none because it would be trusted — enforcement is review plus per-call-site criteria.

**The no-file-contents rule is about FIELDS, and `error.stack` is an ACCEPTED exemption (user decision, 2026-07-23):** `log-foundry` attaches `traceback.format_exception` to every failed span unconditionally and it walks the `__cause__` chain, so a quoted cell (a polars parse error naming the value it could not convert) reaches `error.stack` regardless — suppressing `detail` does not help (see the per-plane entry below for the `detail` audit) and neither does fixing the raise site (`raise … from exc` is what puts it there). Rather than close it (an upstream `capture_stack=False`, or a strip in the sweep), the decision is to **accept it**: `logs/` is admin-only, and a stack is diagnostic metadata an admin debugging a failed run needs, so the absolute rule binds a **field a verb chooses to emit** — not an automatic traceback. **Do not read a stack trace as licence to relax the field rule.** The characterisation test (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`) is kept as a **tripwire, not deleted**: if it starts *failing*, `log-foundry` began stripping stacks and this decision should be revisited in the open.

**The catalog surface names two values the rule reaches that nobody expects it to (SPEC-199), and it is the API that made them reachable.** Both are *arguments to an AWS call*, which is the shape a helper stamping "good telemetry" grabs first. **The SQL statement is never a field value:** user values are interpolated into SQL through `sqlLiteral`, so `WHERE name = 'O''Brien'` *is* file contents by provenance. The span carries `sql_bytes` — the length — and nothing else about the statement. **`stateChangeReason` is never a field value either:** Athena quotes the offending cell back (`Cannot cast VARCHAR 'O''Brien' to INTEGER`), so the reason is file contents by the same argument; the span carries `state` alone. Result rows and column names follow the same split as everywhere else — `row_count` and `column_count`, never the cells. **The `error.stack` exemption above does not cover any of these**, and reading it as though it did is the mistake this paragraph exists to stop: the exemption is for a traceback the library attaches automatically, and these are fields a call site *chooses* to emit, which is precisely where the absolute rule binds.

**The `error.stack` exemption covers FILE CONTENTS and not CREDENTIALS, and the API scrubs rather than exempts (SPEC-195, 2026-08-27):** the exemption above was reasoned about a polars parse error naming a cell it could not convert — diagnostic metadata an admin debugging a failed run needs, in an admin-only store. That reasoning was never applied to a bearer credential, and the API handles one on every request: a user's ID token is a credential for as long as it lives, and an admin-only store is not a safe place for a live one. Two facts were **measured rather than inherited**, and both narrow the problem. `log-foundry` 0.6.0 exposes **no way to turn stack capture off** — `config.py` offers only `max_stack_bytes`, whose validator rejects any value below 1 — so exemption is unavailable and scrubbing at the boundary is the only answer. And the exposure is **not automatic**: `format_exception` renders each frame's source line, not its locals, and PyJWT's own messages carry no token material. The live route is this repo's own code interpolating the token, or the gateway event whose headers hold it, into an exception message or a log field — so the verifier raises a **fixed literal reason code** and chains the provider exception as `__cause__`, which the API never reads. `max_stack_bytes` is set explicitly at the API and is a **ceiling, not a control**: a reader must not mistake it for the scrub. If a later `log-foundry` offers an opt-out, this is revisited — the tests are not deleted.

**SPEC-137 put EMAIL on the never list** (user decision, 2026-07-23) in the shared module docstring: a username is not sensitive here (it IS the prefix, the tag and the DB name) but an address appears nowhere else, carries no operational meaning, and would be the only personal contact detail in a forever-retained prefix. The hazard is mechanical — a Cognito trigger event carries `request.userAttributes.email`, so **never log a raw event, an attributes map, or any dict you did not build field by field**; `pre-signup` logs the DOMAIN, which is what the rule turns on and is shared by every user of that provider.

## Per-plane instrumentation rules (SPEC-132→137)

**SPEC-132** spent the primitives on all nine data-quality verbs and settled two things the remaining planes inherit. **The `detail` audit is a deliverable, not a reassurance:** every `TerminalError` raise site is read, and any whose `detail` interpolates *parsed file content* logs the reason token and the exception type only — in data-quality that is `inspect-source`'s `_probe_columns` catch-all, whose detail carries a polars parse error that **quotes the offending cell**, and the suppression is unconditional for that verb rather than a denylist of reasons the next reason gets added without. And **a contents-shaped field NAME is banned even when the value is a count** — the tripwire caught `rows=` in `assemble-report` on its first run, so a row count is `row_count`; a field whose safety needs an argument is one whose name should say so instead. Failures are narrated **once per verb**, not per raise site.

**SPEC-133** took it to `control-plane-dlq-drain` (`service="dlq-drain"` — not a control plane, since it spans all four and is nobody's verb) and settled two rules the rollout inherits. **`request_id` is a FIELD wherever one invocation handles many requests, never baggage:** `_reset_baggage()` runs once per invocation, so on a function draining up to 400 messages, baggage would leak one request's id onto the next — the fabricated correlation key SPEC-128 FR-002 forbids. **And one event per item is right or wrong depending on which queue you emit INTO:** the sweep emits into the queue it drains, so per-message events give that queue an undrainable floor; the drain emits to the logs queue and drains the request DLQs, so per-message is correct there. The dead-lettered body is a **permanent forensic record** — redacted (every known token field), size-capped, and ONE serialized field, never re-parsed into fields or a body could shadow `request_id`/`verb`/`service`.

**SPEC-134** promoted the per-plane coverage guard to a **fleet-wide harness** in `control-plane-common`: registering a plane is one `Plane()` descriptor (its glob, service name, expected verb count as a LITERAL so a short enumeration fails rather than passing vacuously, and its decorator expectation), and a verb module is found by **defining a top-level `handler`** rather than by any filename convention. It also settled that **the decorator rule is per-plane and DECLARED**: shared-space verbs notify from inside the handler, so `@traced` is asserted to be their ONLY decorator — adding `notifies_on_failure` there later fails until someone establishes the ordering. And **per-item events are permitted where the bound is STRUCTURAL**: the roster fan-out emits per member because membership is capped at ten Cognito slots, which is the same rule as SPEC-131/133, not an exception to it.

**SPEC-135→137 finished the fleet.** 135 logs Athena's `StateChangeReason` **verbatim** alongside the stable token — that raw text is what would have named the missing `CREATE_TABLE` grant, and a token cannot carry a diagnosis — and moved the DDL poll's transition-only narrative into **`cpcommon.athena`**, since the loop is shared. 137's email decision lives in the field-rule entry above; 137 also verified empirically that **`cpcommon.observability` imports and emits with ZERO env vars** (`cpcommon/__init__.py` has no imports, `clients` lazy-imports boto3), which is what makes the layer safe to attach to functions that lack the six `config._require` variables — one `from cpcommon import config` added to `__init__.py` would arm PR #196's bomb for them. Detail: `spec-delivery/SPEC-132`, `spec-delivery/SPEC-133`.

## No ASL state decodes an error Cause (PR #252, control-plane-wide)

`States.StringToJson($.error.Cause)` raises `States.Runtime`, which is **neither retriable nor catchable anywhere** — not even by a `Catch` on the same state. The `ParseError` `Pass` states that did this killed executions *before* the recorded-failure/notify states on 3 of 4 real error shapes (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — verified live with `TestState`). Terminal states now carry the **raw `$.error` `{Error, Cause}`**; `cpcommon.errors.failure_reason` decodes it in Python. Enforced by `lambdas/control-plane-common/test_state_machines_cpcommon.py`. Related trap: a `Pass` state's JSONPath hard-fails on an **absent key** (a null *value* is fine), so anything a terminal `Pass` names must be seeded on every path — now **enforced by a test** (SPEC-114): every `Pass` reachable from a failure seed may read only keys that seed supplies. It has caught this arc twice (`$.location`, SPEC-112; `$.reportKey`, SPEC-114).

## Notifications (SPEC-058→061)

Per-user inbox at `{username}/user_settings/notifications.json` (array of `{id,message,read,timestamp}` — plus an **optional `link`**, SPEC-113 FR-008: an in-app path the message renders as, gated at render by `isSafeInAppPath` so it can never become an open redirect; absent = plain text, which is every pre-113 producer). **Single-writer:** all mutations (system `create` + user `markRead`/`markAllRead` — **no delete**) go through a **dedicated FIFO SQS queue that triggers the writer Lambda directly** (SQS event-source mapping, batch size 1 — **no Pipe, no Step Function**); per-user ordering via `MessageGroupId` = username. The browser only **reads** the file (+ a **60s background poll** for the unread icon) and enqueues (`sqs:SendMessage`). Anti-spoofing = user-action messages carry the Cognito **ID token**, writer derives `username` from the verified claim (`create` = trusted-producer-only — **enforced since SPEC-206** by the writer refusing a `create` whose SQS-stamped `SenderId` names the portal role; the grant itself is unconditioned and cannot be otherwise, since no SQS condition key reaches a message body). UI = header bell **linking to a `/notifications` page** (not a drawer, not a tab), **10/page**, mark-read/mark-all only. First `create` producer = the **shared-workspace control plane** (SPEC-061; seven lifecycle events, incl. delete fanning out to all members), granted `sqs:SendMessage` on the queue. (**058 write pipeline shipped** — `infra/modules/notifications/` + `lambdas/notifications-writer/`; **059 browser data layer done** — `features/notifications/` read service + `useNotifications` + prefetch; **060 UI done** — header `NotificationsBell` link + `/notifications` page (10/page, mark-read/all, optimistic + Toast); **061 done** — the 062 verb Lambdas emit `create` inline via `notify.emit_notification` (orchestrator role gains `sqs:SendMessage` to the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL` env), best-effort.)

## Every plane notifies on a pre-verb failure, and `failure_reason` is the only decoder (SPEC-152)

All four control planes now carry a `NotifyFailure` state ahead of their terminal `Fail`, reached on
every failure path, invoking a thin per-plane verb that decodes the raw `{Error, Cause}` with
`cpcommon.errors.failure_reason` and emits through the plane's own notifier.

**The gap this closes was named by the repo's own design and closed in one of four planes.**
`@notifies_on_failure` needs handler code to run. SPEC-126's DLQ drain covers requests that never
started an execution. Neither covers the middle: an execution that started and then failed **before or
outside** any verb's Python — a `States.Timeout`, a `States.DataLimitExceeded`, a task-level throttle,
a Lambda that fails at **import**. In that window the user got no notification, no DLQ message, and a
request that never completed — against SPEC-114's rule that the notification **is** the completion
channel, with no admin UI to check and no reason to suspect anything but slowness. Not theoretical:
SPEC-137's nine-day `ModuleNotFoundError` and PR #196's shared-layer cold-start crash are both exactly
this shape.

**A fifth plane cannot ship without it.** `test_state_machines_cpcommon.py` enumerates every
`state-machine.asl.json.tftpl` under `infra/modules/` and asserts each has a `NotifyFailure` Task with
a `States.ALL` Catch, plus that its `RecordFailure` copies `$.error` **whole**. The exemption list is
an empty dict — an entry is a decision to leave users in the dark, not a formality. The second
assertion is not redundant with the throwing-intrinsic guard: a plane could satisfy that one perfectly
by copying `$.error.Error` alone, and every message would silently degrade to the generic.

**The duplicate-suppression mechanism differs per plane, and the difference is forced, not stylistic.**
This state sits on *every* failure path, because the paths where no verb ran cannot be selected for in
ASL — so an ordinary failure would otherwise notify twice.

- **table-builder / table-share** suppress in Python via `_verb_already_notified`, on **one name**:
  `Error == "TerminalError"`. That is the only *positive* evidence available — a verb raised it
  deliberately and the decorator's `emit_terminal` fired — and it is the only case where the
  decorator's message is strictly better, because it carries `err.tokens` (without which a
  `columns_removed` refusal cannot name the columns). Everything else notifies, including an
  exhausted `TransientError`, which the decorator deliberately leaves un-notified — a gap this spec
  therefore also closes.

  **The obvious generalisation is wrong in the dangerous direction, and was caught in review.** An
  earlier version inferred the same thing from the *absence of a dot*: bare class name means a
  handler ran, dotted engine name means it did not. But `cpcommon.config` calls `_require` at
  **module scope** and raises a bare `RuntimeError` — not a hypothetical, this fleet's own recorded
  outage (`lambda.tf`: "check-table-absent: RuntimeError COGNITO_USER_POOL_ID unset", PR #196). The
  heuristic would have suppressed it, silencing the exact class of failure the spec exists to
  report. The set of dot-free names meaning "a verb notified" is unbounded and unknowable from the
  payload; the set meaning `TerminalError` is one string.

  **The price is a duplicate on the unexpected-exception path** — a `KeyError` inside a verb
  notifies through `emit_unexpected` and again here, same generic sentence. FR-002 settles it: a
  duplicate is preferable to none. A guess that suppresses is unrecoverable; a duplicate is a
  papercut on a path that is already a bug.

  **A seeded error must not wear a verb's name.** table-builder's `DiffMissingSeed` (the
  `RouteByChange` `Default`) manufactured `Error: "TerminalError"` for a case where `diff-schema`
  *returned successfully* without a `$.diff` — so no exception was raised and no decorator fired. It
  now seeds `DiffMissing`, because a defensive seed whose whole purpose is the shouldn't-happen case
  is the last thing that should buy itself a `Fail` state and silence. The user-facing text is
  unchanged: neither code is registered, so both render the generic clause.
- **shared-spaces** cannot use that test, because five of its seven verbs emit **no** failure message
  at all and a "did a verb run" guard would restore their silence. It reproduces the verb's **FIFO
  dedup token** byte-for-byte instead (`{requestId}:{action}-failed:{actor}`), so SQS drops the second
  message where a verb already spoke and delivers it where none did.
- **data-quality** is unchanged: `dqcommon` centralises one `FAILURE_STEP`, so its pair already
  collapses on an identical token. Unifying `tbcommon`'s per-verb steps to match would change
  notification behaviour on paths that already work.

**shared-spaces needed structural work, not just a state.** Its seven verb `Catch` blocks carried **no
`ResultPath`**, so the error object *replaced* the state and the verified actor was discarded — there
was no recipient to notify even in principle. They now merge under `$.error`; a `ValidateFailureSeed`
covers the pre-identity path (its Catch cannot carry a `ResultPath` — you cannot merge a key into an
array), and the router's `Default` gets an `UnknownActionSeed` whose **literal** `Result` merged under
`ResultPath` is the one seed form that reads no path and so cannot itself raise.

**`$.mode` on table-builder's `RecordFailure` supersedes the rule that forbade it.** The old test
banned `mode.$` there; its stated *reason* was that `ValidateFailureSeed` did not seed it and a Pass
state hard-fails on an absent key. The ban was never the invariant — the seeding was. `mode` is now
seeded, and the test asserts the general form: `RecordFailure` may read nothing `ValidateFailureSeed`
does not seed. Without it a failed **refresh** tells the user their **create** failed.

**shared-spaces gained a `failure_message` resolver** (`shared-space-common/messages.py`), the last
plane to get one. Its domain table is **empty on purpose**: every reason that can reach this path is a
raw engine name that SPEC-106 FR-008 forbids showing, so what varies is the **action**, not the reason.
Going through `cpcommon.messages.register` rather than hard-coding the clause means a code registered
later renders through the same path.

**No deploy-role IAM was needed, and that was verified rather than assumed.** All three planes' deploy
policies scope `lambda:CreateFunction`, `iam:PassRole` and `logs:CreateLogGroup` to
`{project}-*-<plane>-*` wildcards, and each plane's SFN invoke grant renders from the same `locals.tf`
map the new function was added to. SPEC-143's `load-table-definition` is the live precedent. The
spec's Phase 1 assumed an expansion and sequenced a separate land-and-apply around the self-grant
timing trap; neither was required.

**The cold-start probe is the one gate that would have caught SPEC-137.** `test_notify_failure_import_safety.py`
imports each new verb in a fresh interpreter whose `sys.path` is **exactly** what the deployment gives it.
`conftest.py` puts every shared root on `sys.path` for the whole suite by design, and `update-function-code`
succeeds against a function that cannot import. **Superseded in part by the container image (SPEC-213/214):**
the probe used to grant exactly the layers a function's deploy-table row named, and a wrong ROW failed there.
There are no rows and no per-function layer grants — one image gives every function every shared package —
so that half cannot fire and the probe no longer claims it. What survives is the half that still can: these
verbs must import at all, in a minimal environment. The environment is
**inherited**, unlike `test_layer_import_safety.py` which withholds `cpcommon.config`'s six: these verbs
reach their DOMAIN config through their notifier, whose import-time `_require` is *supposed* to run.
(`cpcommon`'s own six resolve on first access since SPEC-156 FR-004, so they are no longer part of what
an import demands from anyone.) Only `sys.path` is scrubbed, because packaging is what is under test.

**One layer needs a second guard, and only one.** The probe puts layer SOURCE TREES on `sys.path`, so a
module present on disk but absent from a layer's *build* is invisible to it. Every layer copies a
**package** (`cp -r cpcommon`) except `shared-space-common`, which publishes **flat modules** from an
explicit `for m in config casio auth …` list in the workflow — so a new module there ships only if
someone remembers to name it. Review confirmed the gap was live: deleting `messages` from that list left
the entire suite green while the deployed layer lost it. A test now joins the workflow's list against the
directory — SPEC-153 moved it to the packaging harness and generalised it; ~~SPEC-214 moved it again, to
`lambdas/test_image_layout.py`~~, when the harness it lived in went with the function table. **SPEC-214's
next PR then RETIRED it, because the list itself is gone**: `assemble.shared_layout` publishes what a
`lambdas/*-common/` directory holds, so there is nothing a module can be missing from. What now holds
`/opt/python` honest is `test_the_shared_layout_is_exactly_what_the_shared_sources_publish`, which walks
those directories independently of the assembler and compares.

That intermediate move was nearly a silent loss and is worth the sentence, because the trap is general:
the reasoning that first retired the guard — "there is no list any more, the assembler copies the
directory" — was true of where SPEC-214 ENDS and false a PR earlier, while `assemble.shared_layout` still
read the list. Measured on the commit that dropped it: a module planted on disk and absent from the list
passed all 2,388 tests, and importing it lazily from a verb passed the image's behaviour matrix too. The
retirement was safe only once the same plant reached `/opt/python` on its own. See *A layer gate must
check the copy list, not the flag map* below.

---

## A layer gate must check the copy list, not the flag map (SPEC-153)

The packaging harness existed because SPEC-137 shipped instrumented code whose layer attachment was
missing and every gate was blind. It joined each function's **imports** against the matrix **flags**.
That answers "which functions attach the layer" and says nothing about **what the layer contains** —
so adding a module to `lambdas/shared-space-common/`, importing it from a function whose row already
reads `layer: true`, passed every check, deployed green, and raised `ModuleNotFoundError` at cold
start. SPEC-137 again, straight through the gate built to stop it.

**The rule: for any shared code packaged by an explicit per-file list, assert SET EQUALITY between that
list and the directory.** ~~`shared-space-common` was the only such layer.~~ **Superseded by SPEC-214:
there is no per-file list anywhere any more** — the container image's assembler ships what a shared
directory contains, so the rule has no subject left in this repository. It is kept because the *reason*
outlives it: a declaration maintained beside the thing it declares drifts, and the drift is invisible
until a cold start. The set equality survives in a different shape — the assembler's output against an
independent walk of the same directories. Both directions — a module in the directory and not the list never ships; a
module in the list and not the directory fails the `cp` at deploy time. Completing the flag map does
**not** substitute: all nine shared-space modules ship in one layer behind one flag, so a module that
never reaches the zip is invisible to the flag map no matter how complete it is. `LAYER_PACKAGES` was
corrected to all nine anyway, with a comment saying exactly that.

`shared-space-common` was the **only** such layer — every other copied a whole package directory or
pip-installed, so a new module shipped by existing, and those were exempt for that named reason.
~~`test_no_unchecked_explicit_copy_list_was_added` fails if a second one appears, so the exemption cannot
quietly widen.~~ **Retired with the list by SPEC-214**, and nothing replaced it because nothing can: the
exemption it policed does not exist once every shared directory ships what it holds. Its structural
successor is a different guard for a different hazard —
`test_every_directory_under_lambdas_is_a_function_shared_code_or_named_exempt`, which refuses a directory
the assembler cannot classify, so a new one has to be declared rather than defaulting into shared code.
The guard-the-guard habit carried over: every comparison there asserts its inputs are non-trivial first,
because two empty sets are equal.

SPEC-152 shipped the shared-space half of this in
`test_notify_failure_import_safety.py`; SPEC-153 moved it to the packaging harness and generalised it,
rather than leaving two copies of one set-equality to drift apart.

---

## The deliberate twins are discharged: one implementation per cross-plane helper (SPEC-156)

Four helpers were duplicated across the Lambda layers *on purpose*, each with a comment saying so
and naming the condition under which the copies should converge. Those conditions had all expired,
and in two cases the drift the comments warned about had already happened — `dqcommon`'s CAS twin
handled a racing 409 that `casio`'s did not and used a different retry cap, and `cpcommon/auth.py`'s
"one JWKS-verification path for the whole repo" docstring was false because `notifications-writer`
could not import it.

**Decided: `cpcommon` owns the algorithm; a domain layer owns its wording and its constants.** The
conditional-write CAS loop (FR-001), the failure-message resolver (FR-002), the results-location
builder (FR-003), the JWKS path (FR-004), the SQS envelope parser and the Athena DDL runner (FR-005)
each exist once. The domain message modules keep only their **tables**: `cpcommon.messages.Resolver`
gained `prefix`, `access_denied` and `fallback` templates and an opt-in `blank_unfilled`, so a plane
expresses its whole sentence as configuration. `Resolver.__init__` refusing a re-defined base code
is what had kept two planes out — both re-definitions were byte-identical restatements, so deleting
them was a provable no-op rather than a wording change.

**The blocker was `cpcommon.config` resolving eagerly** (FR-004). Six `_require`d environment
variables at *import* meant a function that set three could not import `cpcommon.auth` at all, so it
grew its own verifier. That is the general shape worth carrying: **an eager module-level requirement
does not merely inconvenience an importer, it forces a fork.** Config resolves lazily now and still
fails loudly at first use.

**Byte-identity was measured, not asserted.** Every reason in all three planes was rendered under
every argument combination against both implementations — 2214 messages per side. Exactly one row
differed: `malformed_event` under table-share, a shared base code that plane never declared, which
used to fall to `tscommon`'s unknown-code fallback and now reads what it means. It is unreachable
there today (table-share's only `parse_sqs_request` call raises `unauthorized`), and it is pinned by
a test rather than left to be rediscovered in an inbox. **Reading three implementations side by side
would not have found it** — that is the argument for rendering both and diffing, on any future
consolidation.

**Do NOT** read this as licence to merge the domain layers into `cpcommon`. The packages stay; only
genuinely cross-plane helpers moved.

> **The FENCE stands; its mechanism is superseded by SPEC-214.** There is no attach step and no
> matrix row to change — the image copies every `lambdas/*-common/` package to `/opt/python`, so a
> move between packages is an import change and nothing else. That makes the separation a code
> decision with no packaging left to enforce it, which is a reason to hold the fence more firmly
> rather than less. Full entry: *A guard is retired by proving its replacement, then deleting* in
> [`infrastructure.md`](infrastructure.md).

## The copy is a top-level Distributed Map, and attribution is a verb (SPEC-160)

Sharing a table used to copy every object for a recipient inside **one** `copy-objects` invocation,
inside a `Map` over recipients. The share caps followed from that: `SHARE_MAX_OBJECTS = 1000` and
`SHARE_MAX_TOTAL_BYTES = 20 GiB` were sized backwards from a 900-second Lambda timeout. A user with
several hundred Parquet part files did not get a slow share; they got a refusal that read like a
product decision and was really an implementation detail.

The copy is now a **top-level Step Functions Distributed Map** over a flat `(recipient × object)`
JSON Lines manifest in the admin bucket, batching items into the same copy code as before.

**Top level, NOT nested inside the recipient `Map`.** The nested version is the obvious one and it
buys nothing: it fans out per recipient, so the ceiling stays per-recipient work. One Map over pairs
covers every recipient at once and never raises the nesting question. It costs exactly one thing,
and that cost is this decision's other half: **per-recipient isolation stops being a property of a
Map item.**

**So attribution became a verb, and it reads BOTH result groups.** `collect-transfer-results` reads
the Map Run's `ResultWriter` export. Step Functions files a child by its **execution status, not by
what its payload says** — and the batch copier deliberately **succeeds** while reporting per-item
failures, so those land in `SUCCEEDED_n.json`. A collector reading only `FAILED_n.json` would report
universal success while a recipient received an incomplete dataset **and a table over it**. It
therefore reads `SUCCEEDED_n` (per-item `failures` from the output) **and** `FAILED_n`/`PENDING_n`
(whole-batch failures, attributed from the child's *input*). A record whose payload Step Functions
omitted (`Included: false`) is **unattributable and fails the whole request** — never "no failures
found". One failed item means that recipient gets **no table**: a partial copy under a table
definition is worse than no table at all.

**`ToleratedFailurePercentage: 100` and `STANDARD` children.** The Map Run must always finish, or
there is nothing for the collector to attribute. Children are STANDARD because a batch may hold a
multi-GiB object whose multipart copy exceeds EXPRESS's five-minute ceiling, and EXPRESS's
at-least-once semantics would re-run whole batches.

**A WHOLE-batch failure fails every recipient in that batch, and that is fail-closed on purpose.**
Items are batched in recipient-major order, so a batch spans several recipients only when a
recipient has fewer objects than the batch size — but when it does, a child execution that dies
outright (an exhausted `TransientError` retry, a Lambda timeout) takes all of them down with it. It
reported nothing per item, so which of its items landed is genuinely unknown, and the conservative
answer is the only honest one. Pre-160 each recipient had its own invocation and its own retry
budget, so this is a real narrowing of isolation, accepted deliberately: the alternative is trusting
a copy nobody observed. A Distributed Map cannot partition batches by key, so a per-recipient
guarantee would mean a Map per recipient — the nested design this decision rejects.

**Attribution keys on `(kind, name)`, never the name alone.** A destination is a pair, and nothing
in this system stops a shared space being named after a user (the archival arc records the same
hazard for its key layout). Keyed on the name, one failed object in space `acme` would deny user
`acme` a table they actually received, and send them a failure notification for it.

**The export is reconciled against the manifest, not merely parsed.** Every unrecognised shape
raises — an entry naming no object, a result file that is not a list of records, a record with no
item count — because a reader that skips what it does not understand reports a clean run over an
export it never read. Shape checks alone are not enough, though: a well-formed export can still
cover only some of the batches, so the collector requires the item count the export accounts for to
equal the count `build-transfer-manifest` wrote. Anything less is a whole-request failure.

**The raw `{Error, Cause}` is decoded at the collector and NOT carried onward.** This is a payload
decision. A Cause runs to hundreds of bytes with its stack; leaving `guardResults` on the state
*and* re-emitting the raw error in the outcomes would put three copies of every refusal on the state
by the time the finish Map merges its results — measured at **108% of the 256 KB limit** for 50
conflicting recipients, which is the *ordinary* case of re-sharing a table most recipients already
have, and a breach there lands **on a Map** and destroys every per-recipient outcome. So the
collector **consumes** `guardResults` and carries `cpcommon.errors.failure_reason`'s decoded code;
the raw object remains in the execution history at the state that produced it. The two peaks — the
guard Map's output and the finish Map's — are both modelled by
`test_the_whole_map_state_stays_under_the_payload_limit`, at 42% and 45%.

**A deterministic item failure never raises; a transient one always does.** The batch returns
per-item outcomes and succeeds, so one unreadable key never costs its 49 siblings their copy. A
throttle raises after every in-flight copy settles, and the Map retries the whole batch — safe
because copy is idempotent and the conflict guard has already run. The `CopyObjects` child state
carries **no `Catch`**: catching there would SUCCEED a failed child, filing it under `SUCCEEDED_n`
with no per-item failures, and every item in it would be reported as copied.

**The manifest key is execution-unique; the copy plan beside it is deliberately not.** A plan is a
pure function of the request, and two overlapping executions colliding on one plan key is harmless
because both plans describe the same object set — that argument is written out in `plan_key`'s
docstring and still holds. It does **not** carry to the manifest: its lines depend on which
recipients the **guard accepted**, which is time- and destination-dependent, so a shared key would
let one execution's Map Run copy for a recipient the other's guard had just refused as `conflict`.
The execution name is stamped by a **Pass** state (SPEC-157's measured pattern: reading `$$` in a
task's own `Parameters` wraps the payload, and every notify path here reads the request at the top
level).

**The Distributed Map's permissions are the STATE MACHINE role's, not the Lambda execution role's.**
It is the state machine that calls `StartExecution` for each child and that reads the `ItemReader`
object and writes the `ResultWriter` export. Putting them on the execution role renders green,
applies green, passes a policy-render test, and fails on the first real share with `AccessDenied` at
the `ItemReader` — naming a role nobody was looking at. `StopExecution` is not granted;
`StartExecution` + `DescribeExecution` is the documented least-privilege pair. A test asserts the
`states:` actions appear in the SFN policy and **not** in the execution policy.

**The engine lives on `cpcommon.transfer`, not `tscommon`.** SPEC-164→167 (send files) is the second
caller and SPEC-168→172 (archive) the third; SPEC-156 already settled that `cpcommon` owns the
algorithm while a domain layer owns its wording and key layout. `tscommon.copy` was **deleted**, not
wrapped — a re-export shim is the deliberate twin that spec exists to prevent. Table-share keeps the
manifest **key layout** (`copy_plan.transfer_manifest_key`) and every user-facing sentence.

**S3 Batch Operations is rejected, not deferred** — see the amendment on the *Table Share* entry
above. The refusal is a property of the API (`TargetKeyPrefix` prepends to the full source key; 5 GB
per object; one destination bucket per job), not of the implementation it was proposed to replace.

**The caps did not move.** 160 changes the mechanism and nothing a user can see: same push, same
conflict rules, same notifications, same `SHARE_MAX_*`. That ordering is deliberate — a regression in
a new engine must not be able to hide behind a new limit. SPEC-161 raises the ceiling.

**Two numbers live in two places, and a test holds them together.** `MAX_ITEMS_PER_BATCH` and
`MAP_MAX_CONCURRENCY` (20) are read by the batch verb from `cpcommon/transfer/config.py` and by the
rendered ASL from `locals.tf`, because Terraform cannot import Python. The batch size is sized
against S3's *worst case* — two 1024-byte keys and two 63-byte bucket names put an item near 2.3 KB,
so even 50 items sat under half the 256 KB child-execution input limit — and that bound is
**computed in a test**, not asserted as a number.

> **Superseded (SPEC-161, 2026-08-10) — `MAX_ITEMS_PER_BATCH` is 8, and the PAYLOAD bound is no
> longer the binding one.** `ItemBatcher` batches by **count, never by bytes**, so the unit that
> must copy inside `copy-objects`' 900 seconds is a whole batch. That was implicit while
> table-share's total cap was 20 GiB — a batch could not exceed the whole table — and SPEC-161's
> 1 TiB removed it.
>
> **And a batch's cost is a MAKESPAN.** `copy_batch` hands one whole object to each of
> `COPY_CONCURRENCY` workers and `copy_one` part-copies serially, so the cost is
> `ceil(items / COPY_CONCURRENCY)` rounds of the slowest object — never total bytes over an
> aggregate rate. **8 = `COPY_CONCURRENCY` makes that ceiling one**, so a batch costs one object's
> time (429 s at `SHARE_MAX_OBJECT_BYTES` 10 GiB). At 10 items it was two rounds and 859 s against
> a 900 s timeout; the bytes-over-bandwidth reading called the same configuration 537 s and stayed
> green. `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the makespan and
> `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality. **The batch size,
> `COPY_CONCURRENCY` and table-share's per-object cap can no longer be changed independently.**

## A post-identity failure needs its own seed, and the fleet guard cannot see it (SPEC-165)

**Decision.** The file-send machine carries **two** failure seeds. `InspectSource`'s catch uses
`ResultPath: "$.error"` and routes to `InspectFailureSeed`, which supplies `raw` from
`$$.Execution.Input` and the actor from `$.actor`.

**Why not route the catch straight to `RecordFailure`,** which is what every other plane does. This
plane's `RecordFailure` reads `$.raw`, and `raw` exists on **no** post-validate state — SPEC-164
deliberately did not thread the request through, because the Pipe record carries the selection
again as an escaped string. A Pass state's JSONPath hard-fails on an absent key with an uncatchable
`States.Runtime`, so the direct route kills the execution **before** `NotifyFailure`: the sender
hears nothing, on exactly the failures SPEC-152 exists to report.

**Why the fleet guard does not cover it.**
`test_a_failure_seed_supplies_every_key_the_failure_terminal_reads` identifies a seed
**structurally**, as a Pass whose `error.$` is `"$"` — the shape a catch has when the error
*replaced* the state. A catch carrying a `ResultPath` produces `"$.error"` instead, and the fleet
walk skips it entirely. Widening that detection is a fleet-wide change to a guard, on five machines,
and was **rejected as out of scope for this spec**; the plane's own suite compensates with a walk
that derives from the machine what Step Functions actually leaves on the state at each catch
(`ResultPath: "$.x"` ⇒ the task's input plus `x`; no `ResultPath` ⇒ nothing addressable). Verified
by mutation — and the first version of that walk **passed vacuously** on the exact mutation it
existed for, because it treated the catch target as a seed instead of as a reader.

## The machine's ceiling cannot notify on its own, and this plane's timeout door needs a fallback (SPEC-166)

**Decision.** A top-level `TimeoutSeconds` of 10,800, shipped together with an EventBridge rule on
`Step Functions Execution Status Change` / `TIMED_OUT`, a second door in `fs_notify_failure`, that
verb's raise to 60s, and the deploy role's `events:` grant.

**Why together.** AWS catchers cover Task, Parallel and Map states but **not top-level execution
failures**: the timeout terminates the run outright, so no state runs, no `Catch` fires, and the
machine's own `NotifyFailure` is unreachable on the one failure it most exists for. `TIMED_OUT`
only, never `FAILED`, or every caught failure notifies twice.

**The budget is computed, every term of it**: copying 6,597 s + per-child overhead 939 s + guard Map
600 s + serial verbs 735 s = 8,871 s against 10,800 s. The only input without a measurement behind
it is the per-**round** child overhead — charged per round because slots pipeline — and it is
load-bearing: charged per child at even half a second the budget would blow. The test states its
own break-even (~9 s per round).

**The door needs a fallback table-share does not.** EventBridge caps an event at 256 KB and Step
Functions drops the input rather than exceed it, while `SEND_MAX_ITEM_BYTES` deliberately allows a
Pipe record approaching 200 KB — so the sends most likely to time out are exactly the ones the
event alone cannot attribute. The door reads the input back with `states:DescribeExecution`, on the
**Lambda execution role**, because EventBridge invokes the notifier outside any execution.

**And the seed that reports all of this must not carry the request twice.** `RequestFailureSeed`
supplies `$.raw` (the Pipe record, ~200 KB at the cap) and **not** `$.source`, which is the same
selection again: together they breach the 256 KB state limit for a quote-heavy legal request, on a
Pass with no `Catch`, killing the run before `NotifyFailure` at the end of a three-hour copy.
Nothing on the failure path reads the source; an operator has it inside `raw`.

## The lock protocol is `cpcommon`'s, extracted ahead of its second consumer (SPEC-187)

SPEC-187 needs a per-space lock, which made the file-operations plane the second consumer of a
protocol that had lived on `tbcommon.table_lock` since SPEC-157. Copying it would have left **two
full compare-and-set lock implementations in the fleet** — the deliberate twin SPEC-156 spent a spec
discharging, in the one module whose entire purpose is preventing a concurrency bug.

So the protocol moved to `cpcommon.lock`, parameterised by bucket, key, stale threshold, wording and
identifying fields; each domain keeps its key layout, its own thresholds and its own sentences. It
was extracted **ahead of** the second caller rather than after it, which is this repo's recorded
pattern: building the caller first means importing a leaf domain's module, and that is the
undeclared shared layer SPEC-155 had to unpick.

**Two seams the shape had to grow, both forced by what a caller's tests need.** The reader is
**injected**, called as `read(key)` — pinning the read is the only way to reach the concurrent case,
two acquires seeing one stale tag decided by the compare-and-set rather than the age check. Had the
protocol read S3 itself, that seam would not exist and `test_two_simultaneous_steals_and_only_one_wins`
would have degraded into two sequential calls that still pass every assertion, which is worse than a
failure. And the wording is **six sentences plus a fields mapping**, not one label: the six are
emitted from seven call sites with different fields, and a caller's tests assert them by message.

**The proof of behaviour preservation is that table-builder's two lock suites were not rewritten.**
One assertion did have to move — a grep for `delete_object` pointing at a module that no longer holds
any write code, which would have kept passing while asserting nothing.

## The engine's attribution vocabulary belongs to the CALLER, not to cpcommon (SPEC-189)

`cpcommon.transfer.copy_batch` and `results._from_input` built their failure records as
`{recipient, kind, reason}`, hardcoded to table-share's vocabulary. This plane attributes to a
**selected item**, and there was no field to carry it: an `itemKey` on a manifest line rode into the
child input and was dropped on the way out. The engine now takes a caller-supplied `echo_fields` set
in **both** halves — they are separately implemented, one copying what the batch verb wrote and one
rebuilding it, which is exactly the pair that drifts, and a drifted record is one the caller
silently cannot attribute.

**`echo_fields` has no default.** A default hands a new caller either table-share's vocabulary or an
empty set, and both are wrong without a review. Table-share and file-send pass
`("recipient", "kind")` and their records are byte-identical, measured by rendering both rather than
argued. **Archive passes the empty set and its records change**: its manifest carries neither field,
so every archive failure used to read `{"recipient": null, "kind": null, …}`. A named test says the
two nulls are gone on purpose.

**The echoed fields must stay bounded.** The list rides the exported result and then the state, where
a key list is the unbounded term that breaches the 256 KB limit **on the Map** — destroying every
per-item outcome the export exists to preserve. Echo a name, never a key set.

## Two budgets, and both were wrong before they were computed (SPEC-189)

**The joint budget:** the lock give-up, two guard sweeps, every serial verb timeout, the copy's
makespan and the deletion, added. At 3 TiB it came to ~12,700 s against a 10,800 s ceiling — and the
earlier version carried **no give-up term at all**, though a waiter can spend 2,080 s. Waiting for a
busy space and *then* copying is one execution, not two scenarios. **The cap moved to 2 TiB, not the
ceiling**, because the ceiling also sets `STALE_LOCK_SECONDS` and a longer stale window on a shared
space blocks everyone who works in it, not only the person whose run wedged.

**The state budget, which no earlier spec owned:** the deletable list, the per-item counts and the
per-item deletion records measure **287,532 bytes** at the selection cap against 262,144 (307,083
with conflict samples). All three travel by pointer, on this plane's own recorded rule that
everything unbounded on the state does. Where it would have broken is the worst place available:
`States.DataLimitExceeded` on the collector's result lands **after the copy**, and on delete-source's
**after the deletion**, and that error escapes every `Catch` — so the user would be told nothing at
all about an operation that had already moved their data.

## One producer, after the release, reached from BOTH of ReleaseLock's edges (SPEC-191)

The plane's outcome producer is the last state before `Succeeded` and it sits **after**
`ReleaseLock` — before it, the space would be held for as long as the messages take to write. The
half that is easy to miss is that `ReleaseLock`'s **`Catch`** had to move with its `Next`. That
catch exists so a failed release cannot fail a request that did its work; pointed at the terminal,
it skips the producer, and a release whose `Retry` one throttle exhausts then **completes the
operation and tells the user nothing**. The browser's per-space gate, which settles on a
notification carrying the `requestId`, would hold that space until the machine's ceiling — the exact
wedge the always-present `requestId` exists to prevent, arriving through the one path nobody looked
at. Both edges reach the producer now, and a test asserts it.

**It is also the one Task on this plane whose catch reaches a terminal rather than a release**, and
that is not an oversight to be tidied. The lock is free by the time it runs, and a release is an
**overwrite**, not a compare-and-set on the holder — so a second one would clobber whichever
execution had since acquired that space. The graph walk's not-under-the-lock set names it with the
reason, beside validate-authorize and the failure notifier.

It cannot fail the run: `ResultPath: null` on the state *and* on the catch, and **no**
`@notifies_on_failure` — by the time it runs a `move` has already deleted its sources, so a raise
would report a completed operation as a failed one. And it reads the **state and nothing else**: a
verb that loaded the plan would join the set whose smallest memory sizes `FILE_OPS_MAX_OBJECTS`,
shrinking a cap that has nothing to do with notifying. A test derives that set from the source.

## A notification payload is bounded by BYTES, and the binding case is the PLAIN one (SPEC-191)

The inbox is capped at 200 rows and the browser fetches and `JSON.parse`s the **whole** document on
every 60-second poll, from the header bell, on every page — so a worst-case inbox is a recurring
per-minute download rather than a one-off read. Against that, one conflicted item is ~200 bytes at
ordinary key lengths and ~12,000 at this plane's caps: S3 keys are 1,024 bytes of arbitrary UTF-8
and JSON escaping turns a control character into six. A count of three is therefore either
negligible or 36 KB, and the count alone cannot tell those apart.

So the payload is bounded by **bytes as well as count**, enforced at mint by adding conflicted items
only while the serialised payload still fits and setting `more` when any are dropped — for either
reason. That is what makes the pathological case *safe* rather than merely small: a run whose keys
are at S3's limit carries fewer items than the count allows, or none, and says so.

**The budget the byte cap is derived from is the MARGINAL one** — the structured field may not add
more to the worst-case inbox than the row already costs without it. An absolute number would be one
chosen and then defended, and the row's own fixed cost (a percent-encoded link, a 1,024-byte
destination prefix) is not something this spec controls.

**The estimate was overturned twice, and both corrections came from measuring rather than
reasoning.** 4 KiB was written down first. The first measurement refused it — and the binding case
turned out to be the **plain** one, not the escape-heavy one, because a control character expands
*six* times inside the JSON payload and only *three* times in the percent-encoded link beside it, so
the row a payload competes against is **smaller** when the keys are hostile. Then a reviewer found
the second error: that measurement compared the budget against a row **that already carried the
payload head**, which weighs the field against itself. Measured against a row carrying no payload at
all, the allowance is **1,674 bytes**, not 3,047. **The cap is 1 KiB.**

**The head is mandatory, so its one unbounded term is capped separately.** Dropping conflicts cannot
help when the head alone is over budget, and nothing validates the LENGTH of a destination prefix on
the way in — only its containment. Left unbounded, a hand-crafted envelope with a multi-kilobyte
prefix would push the payload past the writer's ceiling and lose the **whole message**, on the queue
whose dead-letter queue is deliberately undrained, after the data had already moved.
`FILE_OPS_NOTIFIED_PREFIX_BYTES` is S3's own key limit: a prefix longer than a legal key cannot
produce a legal destination key, so the run it describes copied nothing and a re-submit of it would
be meaningless.

**The producer's bound and the writer's refusal are two numbers in two languages.** A payload the
producer considers fine and the writer refuses does not lose its conflict list, it loses the
**whole message** — on the one queue whose dead-letter queue is deliberately undrained. So
`notifications_writer.MAX_PAYLOAD_BYTES` **rejects** (never truncates) an oversize payload, and a
test reads that ceiling back out of the Lambda and asserts the largest payload this plane can emit
sits under it.

## The run's ONE sentence opens neutrally, because its residue is not all failure (SPEC-191)

Partitioning a run's outcomes into "the operation's success outcome, or not" is the obvious split,
and it makes the sentence contradict itself on the two outcomes that matter most.

A **`duplicate`** reached the destination — the notification's own link points there — so an opening
of "Nothing was moved" is false, and it is followed two clauses later by "This data is now in both
places". A **`noop`** is a success that did nothing, which this plane's vocabulary says in as many
words; reported as a denial it reads as exactly the failure the wording rules exist to prevent.

So the opening is `N need your attention`, which is true of every member of the residue and is the
only thing they have in common. What succeeded is still named first on a mixed run — "2 of 5"
answers the question a user actually has, where a message listing only refusals reads as though
nothing worked.

## A resolved space carries its own IDENTITY, not only its location (SPEC-191)

`authz` resolved a space to `{bucket, root}`. A root is not a name and a bucket is not a kind, and
the difference surfaces only at the far end of the plane: the producer has to say which space a run
touched and link into it, and a re-submit built from that notification needs the **source** space,
which no absolute key contains.

Left as it was, `kind` and `name` reached the summary as `None`, the link builder refused to mint
anything, and **every notification shipped with no link at all** while the payload carried nulls
where a re-submit's spaces belong — with a full green suite, because every fixture in the notifier's
tests hand-wrote the shape it wanted. That is the test-that-cannot-fail class: the fixture asserts a
shape the producer does not emit.

They ride from the resolver rather than being re-read off the request, because that is the point at
which the claim has been **authorized** — a later verb reading the untrusted body would be naming a
space the actor may never have been granted. The guard against the fixture problem recurring is one
test that builds the notifier's input from the real `authorize_source` and the real finaliser
instead of a literal.

## `requestId` rides on every row, including a clean run's and a failed run's (SPEC-191)

A reader settles its in-flight record by matching it, and a clean run has nothing to re-submit — so
scoping the field to "what a re-submit needs" would leave successful operations unsettled. The same
argument applies one path over, to a run that **failed** before the producer ever ran, which settles
nothing otherwise; so the two failure emitters carry a minimal `{requestId}` payload too. That is
beyond the spec's own acceptance criteria and was built deliberately.

## The outcome link: destination, source, or the common folder of the items' PARENTS (SPEC-191)

A copy or move that landed anything links to the **destination**; anything else links to the
**source**, because that is where the items still are. One message per run means one link, so the
rule is about the run rather than about an item — and a `duplicate` counts as landed, since its
objects *are* at the destination and that is exactly where the user has to look to choose which copy
to keep.

**A `delete` links to the deepest folder its items shared, computed over the items' PARENTS.** Over
the keys themselves, a single-item delete yields the item — linking the user into the folder that
was just removed, an empty listing where a folder used to be. Taking parents first makes the
one-item and many-item cases the same computation. A common prefix is also cut back to its last
slash: two siblings named `report-a` and `report-b` share `report-`, which names no folder.

**`?space=` is minted FIRST, and that is not cosmetic.** `NotificationRow` gates the shared-space
variant on the literal `?space=`; the other parameter order slips the gate, the route never reads
the space, resolves the personal one, discards a prefix that does not start with it, and lands the
user in their own files with no banner while the message names a shared space.

**This is the fleet's first link built from an arbitrary KEY**, so the prefix is **percent-encoded**
at mint — every other plane interpolates catalog-constrained names. An unencoded `?`, `#` or `&`
truncates the link into one that resolves elsewhere, and the browser's `isSafeInAppPath` cannot see
it: that guard inspects only the first two characters.

## The outcome wording reuses the failure bodies and is deliberately NOT a resolver (SPEC-191)

Six per-item outcomes carry a reason the failure table already words — `source_missing`,
`source_empty`, `copy_failed`, `source_changed`, `source_delete_failed`, `delete_refused` — so the
item clause resolves through that same table and only the outcomes with no body of their own are
written out. A second table would be one code with two sentences, inside one module.

**The outcome table is not registered as a `Resolver`.** `Resolver.__init__` ends by marking every
key it is given a globally valid reason code, so registering these would let
`TerminalError("duplicate")` pass raise-time validation — undercutting `outcomes.py`'s rule that no
member of the per-item vocabulary may ever be a whole-request failure reason. That a success
sentence cannot open with "Couldn't move that: " is the lesser argument.

## A pre-existing notifications spoofing gap, recorded and not fixed here (SPEC-191)

> **Superseded by SPEC-206 (2026-08-24).** The gap below is closed: the writer refuses a `create`
> whose SQS-stamped `SenderId` names the portal role. The grant is still unconditioned — that part
> stays true, and is why the control is a runtime one. See the SPEC-206 entry at the end.

The portal role holds an **unconditioned** `sqs:SendMessage` on the notifications request queue, and
the writer takes the body's `username` verbatim for a `create`. A signed-in browser can therefore
already plant a notification — message and clickable in-app link — in another user's inbox. The
comment directly above that IAM grant asserts the opposite, which is the dangerous combination: a
reader checking the IaC is told the hole is closed. IAM cannot condition on a message body, so the
fix is a second queue or a token on `create`, and it changes a plane seven features share. Recorded
rather than absorbed into this spec; the payload ceiling above is the only part of it this spec owes.

## The notifications `create` boundary is a runtime check, because IAM cannot express it (SPEC-206)

The plane has said since SPEC-058 that `create` is trusted-producer-only, and the writer takes the
body's `username` on that action — correctly, because a plane notifying a *recipient* holds no token
for the person it is telling. **The IAM policy never implemented it.** The portal role's
`sqs:SendMessage` on the notifications queue was unconditioned, so any signed-in user could enqueue a
`create` naming anybody and saying anything, including a clickable in-app link. The comment above that
grant asserted the opposite, which is the dangerous combination: a reader checking the IaC was told the
question had been answered.

**IAM cannot express this rule at all, and that is the argument — not a preference for runtime checks.**
No SQS condition key reaches a field inside a message body, so a queue or identity policy could only
deny the portal role `sqs:SendMessage` outright: the same principal on the same action that `markRead`
and `markAllRead` need. There is no policy that permits two of the three actions. So the boundary is the
`SenderId` SQS stamps on every message — a message *system* attribute the service sets and a
`SendMessage` cannot — compared on the **role-id half**, the substring before the first `:`. Not
equality against the whole value (which never matches, and a control that never matches reads exactly
like one that works) and not `startswith` (which would refuse an unrelated role whose unique ID merely
shares an opening). The session-name half is never examined: Cognito's enhanced flow does not document
what it puts there.

**The rule is a DENY of one principal, not an ALLOW of the rest.** The grant is held by every
control-plane execution role, the DLQ drain and the portal role — and exactly one of them is
user-reachable, which is what makes a single-principal refusal complete rather than partial. The
count is deliberately not written here: it moved with the eighth plane, and it will move again. An allow-list would be a
hand-maintained list of role IDs that fails closed on the day a plane is added: that plane's
notifications would stop, drop or dead-letter unnoticed and nobody would connect the two. One
environment variable beats eight, and the deny direction fails open only toward principals that require
an explicit IAM change to exist.

**A refusal LOGS AND DROPS; it does not raise.** Raising would cost three invocations and one permanent
dead-letter message per forged request, on the queue whose DLQ SPEC-126 deliberately leaves undrained
and which is this plane's only operator-facing signal — handing every signed-in user a way to drown it.
The structured `observability.error` therefore *is* the signal, and has to be, precisely because nothing
accumulates to notice. It carries the reason code and the SQS `messageId` (both service-stamped) and
**nothing from the body**: echoing it would move the injection from the victim's inbox to the operator's
log rather than remove it. The guard sits **above** `_resolve_username` rather than inside the `create`
branch, because that call runs before any branch — lower, a forged create that simply omits `username`
would reach `create requires a username` and raise, which is the vector the drop exists to close.

**Three reason codes, not two.** `untrusted-sender`, `sender-id-absent` and
`sender-check-unconfigured`. A check that cannot run must not report a pass, and the cases are
operationally opposite: one is somebody trying it on, one is the control having broken, one is the
deploy being wrong. Splitting the third out is also load-bearing, and two guards carry it: the
empty role-id half is refused **before** the comparison, so an absent sender never compares equal to an
unset variable and gets logged as a forgery; and the configuration is tested **first**, so an unset
variable reports itself even when the sender is absent, rather than returning `sender-id-absent` and
blaming the message for a broken deploy.

**Do NOT split `create` onto a second queue.** It is the obvious fix — IAM could then enforce this with
no runtime check — and it is rejected. The single-writer guarantee is *one FIFO queue, one message group
per user, batch size 1*, and FIFO ordering is per `(queue, group)`. Two queues means two event-source
mappings and two concurrent invocations read-modify-writing one user's `notifications.json`: a mark-read
and an arriving notification can lose each other. It trades a spoofing bug for a data-loss bug, and
closing that would mean putting the inbox write under ETag CAS first.

**Two limits, stated rather than implied.** This decides who may send a `create`, not who may reach the
queue — a non-JSON body or an unknown action still raises from `_parse_record` and dead-letters. And it
is the **interim** fix: Arc B removes the browser's grant (SPEC-200) and after SPEC-196 the denied
principal becomes a *service* principal, harmless because every `create` is emitted by execution roles.
The check stays regardless; that removal is eleven specs out and reversible. Detail:
`spec-delivery/SPEC-206`.

## A delete removes people, not things — and retention keys on a durable fact, never live status (SPEC-205)

Deleting a shared workspace ends every member's access, the owner's included, and destroys nothing:
the objects, the Glue database and the registry record all survive, and the record keeps
`status: "active"` with an empty roster. The bucket has no versioning, so the behaviour it replaces
could not be undone at all; this one is undoable by an administrator. Two costs are permanent and
product-visible, and both are said where users can see them: **the name is never reusable**, because
the record that locks it is never released, and **data a user asked to delete is retained**.

**Retention keys on `everActive`, a durable monotonic field, and not on live `status`.** A status
moves `active → deleting → failed`, and every one of those transitions describes a workspace whose
data is intact — so a route chosen from status destroys live data on a delete that failed once. The
field is stamped by `finalize` **only** on the active outcome, because `finalize` runs on both create
outcomes and an unconditional stamp marks every failed create ever-active, which refuses its owner's
legitimate retry and refuses to tear it down. An AST sweep holds it monotonic: no module may write it
anything but `True`, and `pop`/`del` count as writes.

**`deleting` is NOT evidence that a space was ever usable, and a draft of this spec said it was.**
The reasoning looked sound — only `delete_space` writes that status — but deleting is gated on
ownership and nothing else, since neither the validator nor the authorizer inspects status. So an
owner may delete their own failed or still-provisioning create, and the verb writes `deleting`
*before* any teardown; an invocation that dies rather than raising leaves that status permanently,
because the machine records a failure without writing one. A `deleting` record can therefore name a
space that was never usable. The one-shot backfill stamps `active` **only**, and every other status
is a row a human dispositions — for a `failed` record **the discriminator is the space's resources
and its timestamps, never its roster**, since a failed create can have been added to and a failed
delete of a single-member space is single-member too. Even the resources collide: a create writes its
marker object second and its database third of eight steps, so most failed creates hold both.

> Found by executing it rather than reading it, which is why the criterion it replaces had survived
> two rounds of review.

## One predicate decides who may be destroyed and who may be added (SPEC-205)

`registry.is_destroyable` is the whole shape of the change: `not everActive and status != "active"`.
The delete verb routes on it, and the guard refusing new members refuses on it. They are complements
of each other, and every revision that wrote them twice moved one without the other — each drift
silent, and each in a different direction. Written once they cannot disagree.

**Do NOT re-derive either side.** Keying the add-guard on `status != "active"` freezes additions on a
was-active-now-`failed` record — a live workspace whose owner is mid-recovery. Keying it on
`not everActive` alone freezes them on any healthy `active` record the backfill has not reached, so a
missed backfill surfaces as adds failing on a healthy workspace. The complement of the destroy
predicate has neither blind spot, and that is the only reason to express it once.

Both routes that free a name — the delete verb's never-active branch and `forget`'s owner path —
**re-read before their loop, clear the UNION of the validator's roster and that fresh one, and re-read
once more after freeing the name**, raising if the record came back. A slot outliving its record is a
principal tag on whatever is created under that name next, because the portal policy is scoped on the
tag *value* and not on any space identity.

## The emptied record is inert because the `owner` FIELD is cleared (SPEC-205)

`shared-space-common/auth.py` gates every owner-only action on `actor != registry.get("owner")` — the
field, never the roster. An `owner` retained through a delete would leave the original owner able to
`add-members` on the emptied space and revive it, with the previous cohort's files intact, in one call
and with no confirmation. Clearing it refuses every owner-only action (`actor != None`) and every
member-only action (the roster is empty). `previousOwner` survives for an operator and **no
authorization path reads it**.

**The inert-state test is driven as the ORIGINAL OWNER.** As a stranger it passes over the defect,
because the field `authorize` reads is exactly the one a delete clears.

> **Superseded in part by SPEC-217, for `add_members` and `remove_members` only.** Those two left
> `OWNER_ONLY_ACTIONS` for `auth.member_refusal`, which refuses an emptied record on `emptiedAt`
> **before any actor is consulted** — so for them the inertness no longer rests on the cleared
> `owner` field, and an assertion driven as the original owner would pass as a stranger too. The
> test keeps its discrimination by **pairing** the emptied assertion with a live-record one: the
> original owner allowed, a non-owner refused by code. `delete`, `leave` and `acknowledge_membership`
> are unchanged and still read the cleared field. Full entry:
> [*The operator door widens to member management, and that is a threat-model decision
> (SPEC-217)*](#the-operator-door-widens-to-member-management-and-that-is-a-threat-model-decision-spec-217).

Three further doors are closed, and each was found separately: `_resolve_reserve_collision`'s
failed-retry overwrite additionally requires `not everActive`, or a failed *delete* is re-provisioned
into a revived space with the roster reset to its owner alone; `save_members` refuses an addition to a
record carrying `emptiedAt`, which covers the one record where the owner is back but the members are
gone — a fault after the emptying rewrite restores `owner` so the space stays retryable; and
`cpcommon.registry.is_active` stops being callable outside the module that defines it, because an
emptied space keeps `status: "active"` and the two destination validators used that predicate to
decide whether a space may receive a table or a file send.

**Do NOT call `revoke_portal_role` on the emptying route.** The entitlement design that became `transition_plan.md` §3.11 asked for it and this
supersedes that: with every member's slot cleared the grant reaches no user, and revoking it would
leave a restored workspace's catalog unusable for no benefit.

**The credential window is bounded, accepted, and worse than it used to be — in exactly one place.**
Clearing a Cognito slot ends a membership, but the principal tag is stamped when credentials are
vended, so every removed member keeps live access until their session expires. Under the old
semantics that was harmless: the data was already destroyed. Now it survives, so the window is a
window onto something real. Every browser surface that could reach a retained space derives from the
connections cache, which the delete clears, and both the refresh and the reconcile force a token
re-mint — so the deleter's own window closes within a poll, and a stale `?space=` link falls back
truthfully. **The residual is the query workspace**, which has no active database and takes a fully
qualified `database.table` straight from the editor: a removed member holding a live token can
`SELECT` from, and `DROP TABLE` in, the retained Glue database until it expires. Every other plane
refuses them through `is_active_member`. Recorded rather than fixed, because the fix is the
transition's — an entitlement checked at query time rather than a tag minted an hour earlier — and
because it is the one path by which the thing retention exists to preserve can still be destroyed.

## A control-plane queue may have a second producer, admitted by SenderId (SPEC-208)

Until now one sentence covered the whole fleet: only the API writes a request queue, and every
plane's trust in the `identity` block rests on that. The shared-space queue now has two writers.
The second is `shared-space-transfer-reader`, a scheduled Lambda that turns an operator's CSV into
ordinary requests — the path for the case the UI cannot serve, an owner who has already left.
(SPEC-217 widened that CSV from ownership transfers alone to adds and removals as well; the fence
described here is unchanged, and the threat model it now stands in front of is not — see *The
operator door widens to member management*.)

**The reuse is the point, and it is what forces the fence.** An operator-driven transfer and a
user-driven one are the same verb, the same authorization and the same notifications; only the
door differs. But an operator has no bearer to present, so their message carries **no identity
block** and declares `origin: 'operator'` instead — and the only attributable fact left is the
`SenderId` SQS stamps on the record, a message SYSTEM attribute a `SendMessage` cannot set. That
comparison is the boundary. It is the mechanism SPEC-206 established, inverted: that one refuses a
sender it recognises, this one accepts *only* a sender it recognises.

**What makes the comparison mean anything is that the reader has its OWN execution role.** The
plane's verb Lambdas are a Terraform `for_each` whose `role` is hard-coded to the orchestrator, and
a reader riding that map would make the boundary read "any verb on this plane may forge an operator
request" — true of the running system, and invisible to every test, because a test supplies the
`SenderId` itself. So the reader is a separate resource with its own role, its own environment and
its own log group, and a test asserts it is not in that map.

**`origin` is undeclarable through the API, and that is the first fence rather than a detail.** The
contract refuses a body key it does not declare, so a signed-in caller cannot put `origin` on the
wire at all. Adding it to `SharedSpaceEnqueueRequest` — the obvious way to satisfy the envelope
sweep, which asserts a plane reads nothing the API refuses — would delete that property to make a
test pass, leaving the runtime comparison as the sole fence. The sweep is answered instead by a
named exemption asserting the shape that makes it safe: the plane reads **exactly one** field the
API cannot send, that field is undeclarable, and everything else is still a subset. Same repair the
notifications writer already carries, for the same reason.

**Rejected: a queue resource policy.** It is the obvious way to say "these two principals and no
others" and it is the trap the notifications queue already documents — a blanket `Deny` there
silences every notifying role, invisibly. The access model here stays identity-based.

**Rejected: an in-app admin surface.** The operator path is a file in a bucket and a scheduled
reader precisely so that *no admin group, admin role or admin route* is created. `CLAUDE.md`'s
*no admin UI* fence is unmoved.

**One residual, named rather than left to be found:** an operator gets no notification. Both parties
to the transfer do, and neither names the operator — but the operator themselves has no inbox in
this product, so their only feedback channel is the reader's structured log, one line per enqueued
row. That is recorded in `docs/testing/owed.md` rather than solved.

## A transfer's refusals are RETURN VALUES, because a raise in the validator reaches nobody (SPEC-208)

> **Widened by SPEC-217:** `add_members` and `remove_members` now decide the same way, through
> `auth.member_refusal`, for the same reason and through the same `RefusedSeed` arm — the branch
> was written action-independent, so it needed no change. Read every "a transfer" below as "any of
> the three actions that return", and "every other refusal" as the ones that still raise.

The refusals that still raise on this plane raise `AuthorizationError` from `shared-space-validate`.
That is correct for them and would be silently wrong for a transfer, for a reason that is a property
of the state machine rather than of the code: the validator's `Catch` carries **no `ResultPath`** — you
cannot merge a key into the raw SQS array it was handed — so the state is *replaced* by the error,
and `ValidateFailureSeed` seeds `actor: null` and `space: null`. The notifier treats a null actor as
no trustworthy recipient and stays silent. **A raised transfer refusal is a refusal nobody is ever
told about.**

A transfer's refusals also have to name things the composed failure wording cannot reach. The
notifier is handed an action and a space; "that person is not a member" is useless without saying
*which* person. So the refusal travels as a `(code, message)` pair on the validated context, its
sentence composed in the domain layer at the point that has the name to hand, and a new first
`Choice` branch routes it to a seed that reaches `NotifyFailure` before `Fail`.

**Three traps in that branch, each of which ships green:**

- **`IsPresent` is TRUE for a field that is present and null.** This plane's own
  `ValidateFailureSeed` teaches the opposite habit — "a null VALUE is fine; a missing key is fatal"
  — so seeding `refusal: None` is the natural thing to write, and it would route *every* request on
  the plane into the refusal branch. The validator sets the key only when there is a refusal, the
  rule pairs `IsPresent` with `IsNull: false` so it is right either way, and the happy-path test
  asserts the key is absent. `file-ops` had already paid for this exact trap.
- **The seed cannot go through `RecordFailure`.** That state projects a fixed six-key shape shared
  by all seven verb `Catch` arms, and a `Pass` state's JSONPath hard-fails on an absent key — so
  adding `message` there would raise an uncatchable `States.Runtime` on every one of them.
- **The verb refuses a context carrying a refusal, and the router is not the only fence.** The
  compare-and-swap's expected-owner check is a *lost-update* guard: it asks whether the owner
  changed since authorization, and for a forged operator message nothing about the owner has
  changed, so it passes. Without a check in the verb, any failure of the `Choice` to select the
  refusal branch completes a real transfer. That is this project's named failure shape — the
  failure fails **open**.

**Who the refusal names, and why it is not the operator.** The context's `actor` decides who is
notified, and `notifications-writer` builds an S3 key straight out of it with no validation — while
`"operator"` satisfies the catalog rule that would otherwise catch it. A sentinel there would
address a prefix a real user could own. So an operator-origin request carries the space's **current
owner** as `actor`, with `origin: "operator"` recorded beside it: for a forged message they are the
named victim, and for a fault mid-transfer it is their space. A space with no owner yields no
recipient, which is honest — there is nobody to tell.

**The owner check is skipped by passing `requester=None`, not by a flag.** Written as a flag it
would be untestable: the acting identity for an operator IS the owner, so the check would pass
anyway and the skip could be deleted with every test still green. `None` equals no owner, so
removing the guard makes every operator transfer refuse — loudly.

## A single-verb write pipeline is a queue and a writer, and its DLQ is undrained for a reason of its own (SPEC-211)

Give feedback adds one verb: take what a user typed and append it to that day's file. It gets a
FIFO queue, one writer Lambda and nothing else — no Pipe, no state machine, no fan-out, no
validate-authorize verb. That is `notifications`' shape rather than a control plane's, and the
test for which shape a feature needs is the verb count, not whether the work is privileged.

**It is the first feature built API-first, and that is what makes a submission attributable.**
Every other enqueue in this product began as a browser call to SQS on the caller's own scoped
credentials, and Arc B is porting them. Adding a sixteenth would have been adding work to the port
in the same breath as writing it. So the browser posts to `POST /v1/feedback`, the API verifies
the bearer, and the API sends on **its own execution role** — which means the portal role holds no
statement naming this queue and never did. On the user plane it would have to, and then any
signed-in caller could write a feedback record under whatever username it chose, because no SQS
condition key reaches a field inside a message body. The request type declares no username field,
so there is nothing for the handler to ignore.

**It is NOT one of the ten enqueue routes, and the reason is the wire rather than the plumbing.**
Those carry a nested `identity` block, echo a `requestId` the caller minted, and answer
`EnqueueAccepted`; this carries a top-level `username`, mints its own `eventId`, and answers with
the stamp. Serving it through `apicommon.enqueue` would have meant three exemptions inside a
family whose parametrized guards exist precisely to refuse exemptions —
`_stamped_values`' literal four-route table, the identity-block assertion, and the request-id echo.
For the same reason its queue is **not** in `contract.QUEUES`: that registry is guarded for set
equality with `ENQUEUE_ROUTES` in both directions, so registering it would mean loosening the
guard with a hand-maintained exemption. It reads `FEEDBACK_QUEUE_URL` through its own accessor
instead, and the one thing that costs — the swapped-pair wiring guard — is written out explicitly
in `test_queue_writers.py` rather than left as a gap. What the two DO share is what a failed
`SendMessage` means to a caller, which is why that classifier moved to `apicommon.queue_faults`
rather than being copied.

**Its DLQ is undrained for a reason that is not the notifications one**, and conflating them is
the mistake to avoid: notifications' DLQ is circular, because the drain's only delivery channel is
that very queue. Feedback's is different — the drain resolves its recipient from the verified
`identity` block in the message body, and a feedback body carries none by design. Draining it
would mean notifying whoever an untrusted body field named, which is the exact inversion the
drain's recipient rule exists to prevent. The two reasons are now a mapping in
`_UNDRAINED_BY_DESIGN` rather than a set named for one of them, because widening a set named for
one reason until it holds queues that are there for another makes the name a lie and reduces the
assertion to a transcription of the production value.

**The user's guarantee is deliberately narrow: the 200 means the submission reached the queue.**
Nothing after that point is something a user could act on, which is why nothing after that point
tells them anything — and why leaving the DLQ undrained is consistent rather than a gap. What
exists to notice a death is the writer's invocation-error metric and the messages sitting in a
14-day queue. There is no alarm, because there is no alarm anywhere in `infra/` and adding the
first is a new resource type with its own deploy-role IAM; that is named here as a decision rather
than left as an oversight.

**The writer holds no `s3:ListBucket`, which inverts the fleet's usual rule and is safe for one
specific reason.** A role that cannot list a bucket cannot be told an object is absent — S3
answers `NoSuchKey` only to a caller holding it — so an `except NoSuchKey` branch normally needs a
covering grant. This writer never claims absence: **any** read failure is reported as "no object,
no tag", which makes the following write conditional on `If-None-Match: *`. A transient fault or a
denial then loses its precondition, the loop re-reads, and exhausting the attempts raises so the
message dead-letters. So there is no absence branch to authorize, and the read is dispositioned
`fail-safe-cas` rather than `list-grant`.

**An unreadable day document is raised over, never replaced.** The records are somebody's only
copy and the admin bucket has versioning off, so a writer that "recovered" by overwriting would
lose a whole day to fix one bad byte. The same reasoning SPEC-159 established for an unreadable
settings document, applied where the stakes are a day of other people's words.

**The day comes from the submission, never from the writer's clock.** `submittedAt` is stamped by
the API, is what the `MessageGroupId` is derived from, and is what the key is built from — so the
object a submission lands in was decided when it was submitted, and every message destined for one
day serializes behind the previous one. That is the contention the compare-and-swap would
otherwise have to retry through. A writer that used its own clock would file a redelivered message
in the day somebody is currently reading rather than the day it belongs to, and an unparseable
stamp is refused rather than defaulted for the same reason.

**Rejected: a control plane.** One verb does not earn a queue, a Pipe, a state machine and a
fan-out. **Rejected: any read surface.** No list, no admin view, no notification, no reply — the
records are read with the AWS CLI by whoever wants them, and write-only from the browser's side is
what keeps feedback out of every rendering and escaping question in the app. **Rejected: a shared
DLQ.** A malformed feedback submission must not dead-letter somebody's file operation.


## The operator door widens to member management, and that is a threat-model decision (SPEC-217)

`OPERATOR_ACTIONS` was `{transfer_ownership}` and is now `{transfer_ownership, add_members,
remove_members}`. `shared-space-common/config.py` asked that widening it "be a decision rather than
an oversight"; this is the decision, and what makes it one is that the door changes kind rather than
size.

**What changed about the risk.** Under SPEC-208 a row could only move ownership *between people who
were already members*: it granted access to nobody. A row now grants a stranger live S3, Glue and
Lake Formation access to a space's data. What stands in front of that is **who can write the
inbox** — the `SenderId` comparison is not a second fence against them, only against a forged
message from somewhere else, because a file placed in the inbox is enqueued by the reader role and
therefore carries exactly the sender the boundary accepts.

**That write set is wider than "an operator", and the residual is recorded rather than closed.** The
deploy role holds `s3:*` on the admin bucket (`base/policies/github-actions-deploy.json.tftpl`) and
its trust policy admits `repo:<repo>:pull_request` (`github-actions-trust.json.tftpl`), while
`deploy-infra.yml` runs on `pull_request` under that role. So a PR-triggered job can place a file in
the operator inbox. **Pre-existing and unwidened here** — the same path could already move a space's
ownership — but the consequence is larger now, and a doc that described the door as narrower than it
is would be the more dangerous artifact.

**The authorization opens one PR BEFORE the producer, deliberately.** The plane admits the two
actions while the reader still emits `transfer_ownership` only, so the widening is inert: the only
message that can carry the reader's `SenderId` is one the reader sent. The reverse order would put
messages on the queue that the plane refuses. This is the one place the repo's "grants land before
the resources that need them" rule reads backwards, and it reads backwards for the same reason.

**The owner check moved rather than went.** `add_members` and `remove_members` left
`OWNER_ONLY_ACTIONS` for `auth.member_refusal`, which returns a `(code, message)` pair instead of
raising — a raise in the validator loses the actor and the space, so the refusal reaches nobody, and
until this spec a member change that refused was a request the user watched disappear. `authorize`
gained one explicit `return` covering both and a **terminal `raise`**: two actions are now deliberately
allowed there and gated elsewhere, so the fall-through that used to be unreachable became the
failure mode, and losing the predicate call would be an open door rather than a refusal.

**`requester=None` is the operator skip, and it cannot be a flag.** The validator records an operator
request's `actor` as the space's own current owner, so an owner check written against that field
passes for an operator without any skip — and the skip could then be deleted with every test green.
`None` compares equal to no owner, so removing the guard makes every operator request refuse,
loudly. The same trap one action over is already recorded under SPEC-208.

**Four refusals, one sentence, distinct codes.** Unknown space, emptied, not-active and not-owner are
each true and each answers "does this space exist and who owns it" for any name a signed-in user
cares to try — delivered into their own notification inbox. That is the disclosure this project
declined when it refused to publish a shared-space directory. So a **requester** gets one sentence
that distinguishes nothing while the reason **code** stays distinct on `$.error`, and an **operator**
keeps the detail, because the space's owner is who their refusal reaches and is entitled to it.

> **The same oracle is still open on `transfer_ownership`, and is a named follow-up.**
> `transfer_refusal` composes without the collapse, so `TransferNotOwner` and
> `TransferSpaceUnknown` are byte-distinguishable to a non-owner over any space name. Pre-existing;
> SPEC-217 deliberately did not inherit it into two more actions and deliberately did not smuggle
> its fix in here. `_refusal` already takes the `wording=` argument the narrowing would need.

**Two replay residuals, in both directions.** The schedule is hourly and the FIFO deduplication
window is five minutes, so no two sweeps fall inside one, and replay safety rests on the verbs'
idempotency. What that does not cover is a change made in between: a replayed `remove` removes a
member who was legitimately re-added, and a replayed `add` **re-grants** access to someone the owner
removed. The second is the worse one. Recorded, not solved — the fix is a request ledger the plane
does not have.

**The prefix move was gated on the old prefix being empty, and the gate was run.**
`aws s3api list-objects-v2 --bucket <admin-bucket> --prefix 'ownership-transfers/'` returned no
contents — all three sub-prefixes, not just the inbox — immediately before each of the two merges
that depended on it: the one that re-pointed the reader's code, and the one that narrowed its IAM
and deleted the old lifecycle rules. That order matters in both directions. Once the reader points
at `operator-requests/*`, a file under the old inbox is unreadable by the only thing that could
drain it, in a prefix that deliberately has no expiry; and removing an expiring rule while objects
sit under it leaves them with no expiry at all. Neither hazard had a reaper other than the check.

**A removal does not revoke a live session.** The principal tag is stamped when credentials are
vended, nothing in the fleet revokes a token, and the pool client sets no token validity, so the ID
token's one-hour Cognito default is the window plus the life of any presigned URL already minted.
Revocation is what this door is for, so the reader's own module docstring says it where an operator
reads it.


## A conversion reads the RESULT, never the source, and ownership is a question about a path (SPEC-221)

Saving a query's results as Parquet, JSON or Excel means producing a new file from a result set of
unbounded size, which needs polars and must never run inside a request. Three ways were put to the
user; **he chose a control plane** over building the file in the browser (two dependencies and a
row ceiling the tab's memory sets) and over re-running the query as an Athena `UNLOAD` (a second
bill, several files under names Athena chooses, and no Excel at all).

**The input is the execution's result object.** The tables a query reads are mostly Parquet, some
CSV, some JSON, and it changes nothing: Athena writes every result set as one CSV object under the
actor's own results prefix, so the converter reads one shape whatever was queried, no second query
starts and nothing is billed. **No intermediate file is made** — that CSV exists whether or not
this plane runs, because it *is* the query's result. The path that avoids it is `UNLOAD`, and it
is the one that writes several files.

**A lazy frame over the SOURCE files was considered and rejected** (2026-09-05, user decision) on
four grounds this repo had already measured — no source files behind a view or a saved query,
polars' lazy S3 scan downloading whole objects in Lambda, fidelity lost to re-implementing Trino's
own comparison semantics, and the plane becoming a second authority on table access. The reasoning
is written once, in [`ARCS.md`](../specs/ARCS.md#results-conversion-arc-spec-221--222--223), with
what the result path costs and what the honest remedy would be if it ever mattered.

**Ownership is a question about a path, and that is what makes a guessed execution id harmless.**
An execution is the actor's iff its recorded `OutputLocation` begins with the prefix the API starts
every one of that user's queries with — so `cpcommon.results.user_results_prefix` is one builder
called by both, and a test holds the API's `output_location` byte-identical to it. It is a
**different fact** from `results_location`, which is where a plane's own DDL writes, and the two
are deliberately not merged. An id Athena does not know and an execution written anywhere else
refuse with the **same** code and the same sentence, so the refusal cannot answer "does this
execution exist?" for a caller trying ids. Two things the reviews added: the derived key is refused
if it carries a dot segment, because `startswith` passes a location that then escapes the prefix;
and a non-string space kind is refused rather than raising `TypeError` out of the membership test.

**The write grant is not here.** ~~This plane ships read-only — no `s3:PutObject` Allow
anywhere~~ — **superseded by SPEC-222**, which added `s3:PutObject` and
`s3:AbortMultipartUpload` on the two space buckets beside the verb that writes, exactly as this
paragraph anticipated. What stands is the ORDER, and it is the part worth keeping: the plane
carried the explicit **Deny** on every protected folder in both space buckets from its
first apply — the three `cpcommon.app_managed` declares plus this plane's own non-moving four. Measured against the deployed role: `explicitDeny` for a write under `athenaresults/`,
`archive/`, `shared_tables/` and `user_settings/`, `implicitDeny` for an ordinary path. So the Deny
is discriminating before there is anything for it to override, which is the order that makes a
validator defect unable to write into a receipt folder the day the Allow arrives.

## The converter's shape is decided by what cannot stream and what cannot be retried (SPEC-222)

**The size cap is per format because Excel cannot stream.** Parquet and JSON are `scan_csv` into
`sink_*`, so memory holds a batch and the ceiling is the scratch disk. Excel has no streaming
writer: polars materialises the frame and xlsxwriter builds the whole workbook beside it, at a
peak measured on the fleet image at 23–32x the input CSV. One cap for all three is dishonest in
whichever direction it is set — at Excel's bound it refuses Parquet conversions that work
comfortably, and at the disk bound it promises an Excel conversion that runs out of memory two
thirds of the way through. The caps are recomputed from the measured constants by a test, so a
hand edit to either side is red, and the constants are held equal to the module's `locals.tf`
because the whole derivation is against numbers Terraform has to actually deploy.

**`Convert` retries `TransientError` alone, once.** Every other Task on this plane also retries
the four `Lambda.*` service errors three times, and here that would be a correctness bug rather
than a cost: those errors cover a response lost *after* the function completed, so a retry
re-invokes a converter that already completed its `If-None-Match` `PutObject`, meets its own
object, and reports `destination_occupied` — manufacturing the one refusal the conditional-write
design exists to make truthful. The verb raises `TransientError` only before the upload begins,
and a test reads that from the AST rather than the source text, because the docstring explaining
the rule names the word the sweep looks for.

**A refusal that cannot fire is worse than no refusal.** FR-004 asked for a refusal above Excel's
16,384 columns. It could never run: the described columns travel on a Step Functions state capped
at 256 KB, which a realistic column entry fills somewhere between ~2,500 and ~6,400 columns —
measured across entry widths, and the FLOOR is what a cap is set against. So the ceiling that
exists is the transport's, it is refused in describe-results before the columns are put on the
state that cannot carry them, and it applies to every format. The dead code was removed rather
than kept as a fence that stops nobody.

**Two things polars does silently, both found by measuring rather than reading.** `scan_csv` with
`schema_overrides` whose keys do not match the header RENAMES the columns to the override keys
and applies the types POSITIONALLY, with no error; given a reordered header it keeps the file's
order and matches types by name. Either way a divergence between what Athena reported and what
Athena wrote yields a file with the wrong labels and no complaint, so the header is checked
against the metadata before the typed read. And `sink_ndjson` writes a timestamp as
`2020-01-02 03:04:05.123` — a space separator with trailing zeros stripped, neither ISO-8601 nor
to microseconds — so datetime columns are cast explicitly before the sink.

**The result object is read from the ACTOR's bucket and written to the DESTINATION's.** They are
the same string for a personal destination and different for a shared one, so a suite whose
fixtures are all personal agrees with a converter that has them the wrong way round — which is
what shipped, and what two review frames caught independently. The fake in that verb's tests now
answers the way the IAM grant does, refusing a read aimed anywhere but the user-space bucket.

## A closed vocabulary is type-checked before it is looked up (PR #662, control-plane-wide)

`if value not in SOME_FROZENSET:` reads as a total check and is not one. `in` **hashes its left
operand**, so a request field carrying a list or a dict raises `TypeError` out of the membership
test itself — before the plane reaches the refusal it wrote for exactly this case. The
`@notifies_on_failure` decorator then reports an unexpected error, and the Step Functions record
carries a `TypeError` where a reason code the actor could be told about should be.

**The population was nineteen sites across nine planes, and finding it took three sweeps.** The
first fixed the four `SPACE_KINDS` lookups inline. The second, working from a hand-listed
population, converted the obvious `not in UPPERCASE` forms — and a plane test written for that
change immediately failed on a site the list did not contain, because a **positive-form** test
(`return mode if mode in ARCHIVE_MODES else ""`) hashes exactly the same and no negated-form sweep
can see it. The third missed `action not in config.VALID_ACTIONS` because the vocabulary is reached
through a module and the pattern required an uppercase first character. What settled it was
abandoning regex for an **AST walk over every `Compare` node with an `In`/`NotIn` operator** whose
right-hand side names a constant, which is the only sweep here that cannot be defeated by how the
expression is spelled. The lesson is the sweep, not the fix: a matcher shaped like the examples you
already have finds the examples you already have.

**The remedy is one predicate, `cpcommon.events.in_vocabulary`, not an inline clause repeated.**
At this population size the inline form is how a site gets missed, and each repetition needs its own
test row; one predicate owns one test — including the unhashable case — and every call site's
existing wrong-value test still catches an inverted conversion. It returns a **`TypeGuard[str]`**
rather than a bool, which restores the narrowing the inline `isinstance` gave its callers: without
that, `focommon.authz` stopped type-checking where it passes the kind onward. **Do not read either
type as a fleet-wide guard.** `[tool.mypy] files` lists the shared LAYERS only, so the per-verb
directories — where most call sites live — are not type-checked at all; both annotations bite in
`arcommon`/`focommon`/`fscommon`/`rccommon`/`cpcommon`/`shared-space-common` and nowhere else.
Verified by planting a `str` vocabulary in each: it is an `arg-type` error in a layer and silent in
a verb, where even `_x: int = "s"` passes. It is a **predicate
rather than a raise** because the wording is the domain's — the same bad field means different
things on different planes, and `cpcommon` owns the algorithm while a domain layer owns its wording.

**Five sites that look identical are unreachable and stay as they are**, each checked by tracing
every caller rather than by reading the site: `arcommon.paths` and `focommon.paths` receive the kind
their plane's `authorize_source` already validated; `fscommon.authz.recipient_location` — which is
NOT that plane's `authorize_source` — has one caller, passing a recipient `_normalize_recipients`
built; `feedback-writer`'s category is guarded by the `REQUIRED_FIELDS` loop above it; and
`dq_byte_scan`'s format is derived by `inspect-source` from a file extension and never comes off a
body at all. Converting them would state a defensive intent the callers make false.

**One reachable site is deliberately NOT converted.** `backfill_ever_active` reads `mode` off a
raw invoke payload, so `{"mode": ["stamp"]}` raises `TypeError` where its `ValueError` belongs. It
is an operator-invoked maintenance function on no plane and behind no notifier, so the harm this
fence exists to prevent — a `TypeError` on an execution where the actor's reason code should be —
cannot occur there. Recorded rather than fixed, so the next sweep does not read it as a miss.

**The worst instance was not on a validator.** `ar_notify_failure._mode_from_raw_request` reads the
mode off the untrusted body on the EventBridge timeout door — the only door that must, since a
top-level timeout leaves nothing recorded — under a docstring promising it raises nothing. A
`TypeError` there is an async Lambda failure EventBridge retries, so the notifier of last resort
tells the actor nothing, three hours into a restore. Its sibling reader on the ASL door already
type-checked, which is why the first test written for it passed while exercising nothing: **the two
readers are different doors, and a case driven on one says nothing about the other.**
