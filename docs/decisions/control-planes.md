# Control planes — one pattern, eight planes, and the traps are shared

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries a table pointing at each area's Fences. This file opens with those fences — the traps that
apply green and fail later — and holds the reasoning, the constraints and the explicit "do NOT
build" fences for one area beneath them. **Read the Fences before working in the area, then the
entry you need, not the file.**

## Contents

- [Fences](#fences)
- [The chain a request travels is bounded at its inputs and measured against the limit that binds (SPEC-229)](#the-chain-a-request-travels-is-bounded-at-its-inputs-and-measured-against-the-limit-that-binds-spec-229)
- [Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)](#everything-unbounded-on-the-state-travels-by-pointer--including-the-definition-spec-161-extending-spec-090160)
- [Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)](#every-control-plane-machine-that-can-run-for-hours-declares-a-timeoutseconds-spec-161)
- [Data-quality outcome notifications (SPEC-114)](#data-quality-outcome-notifications-spec-114)
- [Control-plane DLQ drain → user notification (SPEC-126)](#control-plane-dlq-drain--user-notification-spec-126)
- [Structured-logging pipe (SPEC-127→129)](#structured-logging-pipe-spec-127129)
- [Structured-logging narrative primitives & the one-door rule (SPEC-130/131)](#structured-logging-narrative-primitives--the-one-door-rule-spec-130131)
- [The field rule — what may be logged (SPEC-130)](#the-field-rule--what-may-be-logged-spec-130)
- [Per-plane instrumentation rules (SPEC-132→137)](#per-plane-instrumentation-rules-spec-132137)
- [The log-foundry pin, and what a library upgrade owes the code written around it (SPEC-224)](#the-log-foundry-pin-and-what-a-library-upgrade-owes-the-code-written-around-it-spec-224)
- [Where a child span may go, and the four places it may not (SPEC-226)](#where-a-child-span-may-go-and-the-four-places-it-may-not-spec-226)
- [The failure path joins the trace, including where ASL cannot reach the value (SPEC-227, SPEC-228)](#the-failure-path-joins-the-trace-including-where-asl-cannot-reach-the-value-spec-227-spec-228)
- [A run is ONE trace on the success path, and the extractor is a security boundary (SPEC-225)](#a-run-is-one-trace-on-the-success-path-and-the-extractor-is-a-security-boundary-spec-225)
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
- [The destination prefix is relative, and the doubling it invites is refused by nothing (SPEC-223)](#the-destination-prefix-is-relative-and-the-doubling-it-invites-is-refused-by-nothing-spec-223)
- [A closed vocabulary is type-checked before it is looked up (PR #662, control-plane-wide)](#a-closed-vocabulary-is-type-checked-before-it-is-looked-up-pr-662-control-plane-wide)
- [Excel is bounded by cells, because the converter's memory is spent per cell (SPEC-230)](#excel-is-bounded-by-cells-because-the-converters-memory-is-spent-per-cell-spec-230)
- [The logs queue is grouped per event, because a FIFO group is the sweep's ceiling (2026-09-11)](#the-logs-queue-is-grouped-per-event-because-a-fifo-group-is-the-sweeps-ceiling-2026-09-11)
- [The notification sender bounds every dedup id, by digest rather than by dropping it (control-plane-wide)](#the-notification-sender-bounds-every-dedup-id-by-digest-rather-than-by-dropping-it-control-plane-wide)
- [A group id orders the STARTS, not the runs, and what overlap costs on each plane (control-plane-wide)](#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide)
- [A data-quality request id is claimed by one execution before anything is named from it (data quality)](#a-data-quality-request-id-is-claimed-by-one-execution-before-anything-is-named-from-it-data-quality)
- [Notifications deduplicate per recipient, so a borrowed request id cannot drop someone else's notice (control-plane-wide)](#notifications-deduplicate-per-recipient-so-a-borrowed-request-id-cannot-drop-someone-elses-notice-control-plane-wide)
- [A reused request id is told to nobody, because the run holding the id is the one that reports (data quality, file operations, archive)](#a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is-the-one-that-reports-data-quality-file-operations-archive)

## Fences

Shared spaces, table builder, table share, data quality, file send, **archive**, file
operations and results conversion each get:
a **FIFO SQS** queue → EventBridge Pipe → Step Functions → single-task verb Lambdas, **one execution
role per plane** and its own DLQ; `cpcommon` and a domain module are a CODE split, not a packaging
one, since the cutover. The DLQ is the plane's own because the drain names the feature by the DLQ
a request lands on; a malformed body is not what sends a request there, since the plane refuses it
inside the execution the Pipe starts.

**The traps, every one of which ships green:**

- **No ASL state may decode an error `Cause`.** `States.StringToJson($.error.Cause)` raises
  `States.Runtime`, which is **uncatchable anywhere**. Carry raw `$.error`; decode with
  `cpcommon.errors.failure_reason`, the only decoder.
- **Every plane notifies on a pre-verb failure** — a `NotifyFailure` before `Fail`, reached on every
  path, because the no-verb-ran paths cannot be selected for in ASL.
- **A post-identity failure needs its own seed.** A `Pass` hard-fails on an ABSENT key — an
  uncatchable `States.Runtime`, raised *before* the notifier — so a catch may only route to a state
  whose every read its seed supplies, whatever the key is called. Nothing reads `$.raw` any more,
  which is what retired the instance of this that used to bite; the rule is the general one, and a
  fleet guard walks every seed's forward path to hold it.
- **A PRE-identity seed — `"error.$": "$"`, where the error REPLACED the state — supplies LITERALS
  for everything its terminal reads, including `traceparent`.** Omitting the key instead of
  supplying a literal `null` makes `RecordFailure`'s read the uncatchable error this whole rule
  exists to prevent. Everything post-identity reads `$.traceparent`. **Such a failure DOES join
  the run's trace, and not through ASL:** the value is still reachable nowhere ASL can read — that
  half stands and is why the machines are shaped this way — so `RecordFailure` carries the
  forwarded envelope from `$$.Execution.Input` and `notify-failure` parses the traceparent and the
  request id out of it in Python. **"Pre-identity" names the CATCH SHAPE, not the absence of an
  identity**: every validate-authorize failure lands on that seed, an authorized actor's refused
  request included.
- **Everything unbounded travels by pointer**, never on the state, and **a cap is not a substitute**.
  The exception is a value the system did not choose to put there: `$$.Execution.Input` is bounded
  by Step Functions admitting the execution and there is no pointer to it, because nothing wrote it
  anywhere a verb could fetch it. **Every plane's `RecordFailure` now carries that envelope**, which
  is what lets a failure that replaced the state name its own run — so the exception is load-bearing
  on eight states rather than theoretical. What stops it generalising is the cap SPEC-229 supplies:
  **every caller-controlled field on an enqueue request declares a bound**, and the four-link chain
  is measured against the 256 KiB state limit for every route rather than argued about.
- **Every cap is COMPUTED against the budget that sized it** — memory, makespan, or a service
  quota — and it names that budget. A hard-coded number hides a wrong model, and so does the right
  number against the wrong quota: the fleet message cap was derived from SQS's message limit, which
  bounds what the QUEUE takes and not what an execution can carry. **A cap the request must clear
  before a verb runs is computed in PRODUCTION code**, because every per-plane cap runs inside
  `validate-authorize`, after the request that would overflow has already arrived. And **check the
  unit**: bytes on the wire, bytes in the value, and a count are three different questions that
  look alike as integers.
- **`TimeoutSeconds` is TOP-LEVEL and cannot notify on its own**: catchers do not cover top-level
  execution failures, so a ceiling ships **with** an EventBridge `TIMED_OUT` rule (never `FAILED`, or
  every caught failure double-notifies).
- **Past the `Catch`, a raised refusal keeps its reason and loses its `tokens`**, which never reach
  a `Cause`. So a raise names what its verb found — a column, a colliding item, for a refusal of
  the whole request — only when that verb tells it on the way out, as `columns_removed` does; a
  name told further down, by an end producer or `NotifyFailure`, travels on the state as a RETURN
  VALUE. And most planes' `NotifyFailure` drop a `TerminalError` as already told, so one its verb
  did not tell reaches nobody, and so can a validator's untold raise, since not every notifier
  recovers the actor from `raw`. Collapse what a REQUESTER reads, or it is an oracle.
- **Where a plane has an end producer, it is the ONE voice for every per-item outcome** — not each
  verb. Table-share has none, and its verbs each tell the outcome only they know.
- **Locks are objects claimed under ETag CAS**, released by **overwriting**: with `DeleteObject`
  denied, "free" is a state rather than an absence. The holder is the **execution ARN**, because a
  request id is whatever the caller sent, so two executions can carry the same one. A redelivered
  message should not be one of them: reusing an execution name [was measured](../../infra/info/control-plane-shape.md#a-redelivered-message-is-not-a-re-run)
  to return the original run while it is going and `ExecutionAlreadyExists` once it has closed.
  That a redelivery reuses its name is inferred from the Pipe's v5 UUIDs, not proven, so no lock
  relies on it.
- **An `IF NOT EXISTS` create reports somebody's success, not necessarily yours.** It is what makes a
  retry a no-op, and a run that lost a race runs exactly the same no-op — so the statement succeeding
  is no evidence THIS run built the table, and a plane that reports on it alone is speaking for
  whoever won. Table-builder confirms instead: it reads the table back and refuses `table_exists`
  unless the catalog carries the LOCATION, the partition keys and the projection this run declared,
  compared through the parser and the renderer that built the statement rather than a second copy of
  either. Table-share's create is the same statement and still tells both runs they succeeded.
- **A `MessageGroupId` orders the STARTS, not the runs, on every Pipe-fed plane.** The Pipe starts a
  Standard machine `FIRE_AND_FORGET`, and the message leaves the queue when `StartExecution`
  returns, so the next one in its group starts while the first still runs. A plane whose runs must
  not overlap needs a guard of its own: a lock, a conditional write, or a key unique to the run.
  Notifications and feedback are the exception: an event-source mapping drains them, and that does
  hold a group to one invocation. [What overlap costs, plane by plane](#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide).
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
  blanks the two LEGACY token fields, one of which holds a token in any message enqueued before the
  API stopped sending one. Two are undrained:
  notifications (circular), feedback (no identity in its body).
- **File operations are synchronous IFF exactly one file**; the lock is per **space** and its loser
  **waits** (cross-space takes both in digest order or neither); the **space root is refused** as an
  item; the collision unit is the derived destination **key**, and a protected destination is judged
  there as well as at the prefix, since an item's name can land in a locked folder, and every planned
  key is judged against the role's any-depth write Deny before the transfer, as the source keys are
  against its delete Deny; a **403 counts as occupied**; the deletion takes **confirmed plan keys** — a prefix listing orphans an uncopied object.
- **The browser's async switchover consults the routing predicate ONCE**, above every submission
  point, in one dispatcher. The in-flight record is **session-scoped, never persisted**, and settles
  on a notification carrying its request id.
- **Table share CLONES the source definition, never re-infers it**, and pushes without consent.
- **A data-quality notification IS the completion channel** and must carry the report link, because
  the reports folder is hidden. Its runs index is appended under **ETag CAS** — S3 lists
  lexicographically, so a UUID key gives no chronology.
- **Every member sees the roster**; the join acknowledgement is display-only, since access is granted
  at add time.
- **Notifications deduplicate per RECIPIENT.** Most producers key a notice on `{requestId}:{outcome}`, and
  a request id is the caller's choice, so the requests queue's `deduplication_scope` is `messageGroup`
  and every sender's group is the recipient: two notices collapse only when they go to the same
  person. Deduplicated across the queue, a request borrowing another member's id dropped that
  member's notice. [Per recipient](#notifications-deduplicate-per-recipient-so-a-borrowed-request-id-cannot-drop-someone-elses-notice-control-plane-wide).
- **The notifications `create` boundary is IAM and the API first, a RUNTIME check behind the grant.**
  The portal role holds no grant on the queue, and the API's route accepts only `markRead` and
  `markAllRead`. The writer's check names only the portal role, so against the API's own role the
  route is the only fence; the check is runtime because no SQS condition key reaches a message body. It compares the
  **role-id half** of the `SenderId`, and a refusal **logs and drops, never raises** — dead-lettering per forged request would drown its undrained DLQ. The actor
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
  the one format that cannot stream, and its memory is spent per **CELL** — a one-byte NULL costs
  ~250 bytes — so it is capped by a cell count taken from the CSV **before** anything is built,
  while the others are set by the disk. A byte cap alone cannot be both safe and useful, and one
  admitted a result that ran the converter out of memory. `Convert` retries **`TransientError` only**: a `Lambda.*`
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
- **A `@step` goes only where a caller reaches it ONCE per invocation.** Not on a shared function
  called per recipient/member/target — five look eligible and are not; not inside `copy_batch`'s
  worker pool, where `contextvars` do not reach and spans arrive parentless in their own traces;
  and **never under a name any verb in the fleet uses for its own span**, since `function` carries
  both — checking against its *own* verb is a different, weaker claim. A guard
  over decorators resolves the name a decorator is **bound to**: matching rendered text was
  defeated by two ordinary import spellings. The fourth prohibition — **no generator** — is in the
  structured-logging bullet below, since it binds `@traced` too.
- **Structured logging** goes through `cpcommon.observability` only — and "only" includes the
  library's **private names**, which no module outside it and the two named test harnesses may
  reach: one such reach survived as a silent no-op after the name behind it was deleted upstream.
  **No `@traced`/`@step` function may be a generator** — the library refuses one at decoration, so it
  is a cold start that never completes rather than a bad span. The logs queue is FIFO with **one
  message group per EVENT** — a FIFO group gives up ten messages until they are deleted, so the
  group is the sweep's ceiling, and one per service saturated under a single session — swept on
  a schedule, appended under ETag CAS, retained forever. `@traced` outermost — **except the API**, where one decorator sits
  outside it to turn an unpredicted fault into a declared code: a catch INSIDE the span ends every
  failed request successfully and the fault is recorded nowhere. Messages are literals.
  The **`error.stack` exemption covers file contents, NOT credentials**, and it covers **no field a
  call site chooses to emit** — neither a **SQL statement** nor an Athena **`stateChangeReason`** may
  be one, since both quote a user's own cell values back; `sql_bytes` and `state` instead. The API
  **prevents rather than redacts**: there is no scrubber, a handler is never given a credential, and
  an AST sweep is what holds it.
- **A run is ONE trace**, adopted from FIVE event shapes — the state payload, the Pipe envelope,
  a Distributed Map's `ItemBatcher.BatchInput`, an inline Map's `request`, and the forwarded
  envelope a failure terminal carries on the state as `raw`, which is the only one of the five
  reachable when the error REPLACED the state.
  **The shape list is a security boundary**: the body branch fires for a LIST only, because a bare
  dict's `body` is an API Gateway caller's own, and nothing overwrites an adopted trace. Adoption
  comes **after** the per-invocation reset, which clears it; `run_traceparent()` returns the value
  **verbatim**, since rebuilding it re-emits an inbound `-00` as `-01`. A Map's `BatchInput` pair is
  **per-plane** — table-share's state has no `requestId`, so demanding one is `States.Runtime` on
  every share. The failure path is threaded too, since SPEC-227, and the case that could not be
  threaded is CARRIED instead since SPEC-228 — the clause above says how.

## The chain a request travels is bounded at its inputs and measured against the limit that binds (SPEC-229)

A request travels four representations, each capped by Step Functions at 256 KiB: the caller's body;
the Pipe's record, which carries that body as an **escaped** JSON string and is what
`StartExecution` receives; the validated state a verb returns; and, on a failure, the
`RecordFailure` state, which is the record again plus an error `Cause`. It was bounded in one place
and by the wrong budget — `MAX_MESSAGE_BYTES` was the **SQS** message limit less the identity
block, and SQS accepting a message says nothing about Step Functions starting an execution with it.

**Every caller-controlled field now declares a bound on the CONTRACT**, which is the only place the
population is derivable: a template cannot tell a caller's value from a stamped one, so resolving
it there needs data flow across ASL and eight verbs, where reading the contract needs neither. The
rule is unconditional — every declared string or list path either carries a bound or is a finding —
and that catches a field before any template names it. Sixty-eight paths, each with the budget that
sized it.

**Three units, and conflating them is the failure this shape invites.** A bound is serialized JSON
bytes, or the value's own UTF-8 bytes, or a count — and they look alike as integers. An earlier
draft spent `SHARE_MAX_RECIPIENTS = 50` as fifty *bytes*, so the worst case it built carried one
recipient and understated file-send by 7,497 bytes; it also bounded a roster in bytes, which at the
shortest legal username admits two thousand names against a cap of forty-four. The member cap is
**mirrored from `transfer_reader.MAX_MEMBERS_PER_MESSAGE`** rather than re-derived: a second
derivation of the same verb's capacity came out at 100 against its 44, and the looser one would have
let the API admit a request the operator path already refuses as unable to finish.

**`MAX_MESSAGE_BYTES` is re-derived from the state limit** — the `Cause` reservation, a Pipes-record
overhead reservation, the largest plane's `RecordFailure` literals, an escape factor of exactly 2
and stated headroom — in production code, with a guard measuring each reservation against artifacts
the module cannot read (`infra/` is not in the image). The SQS arm survives as the queue's own
ceiling and is asserted **unreachable**, so nobody reads its passing as evidence it fires.

**The `Cause` is reserved at twice its documented length, and that is what moved the caps.** 32,768
is a maximum length in **characters** on the execution-history event shapes, not a byte quota on a
state, and a Cause is a JSON document inside a JSON string on the state — escaped there like
everything else. Reserved honestly, a quote-heavy selection at the old 96 KiB caps reached a
`RecordFailure` of **263,533 bytes (archive) and 271,446 (file-send)** against 262,144, on a `Pass`
with no `Catch` — figures the chain guard computes rather than restates, because the first pair
written here was measured before the units were corrected and was wrong by up to 8 KB. `ARCHIVE_MAX_ITEM_BYTES` is now **89 KiB** and `SEND_MAX_ITEM_BYTES` **84 KiB**, each
pinned tight — one whole kibibyte more and the chain breaches — with the SPA's mirrors moved with
them.

**A fourth live overshoot the spec never named: file-ops measured a quantity nothing produces.** Its
selection cap counted the selection with `ensure_ascii=False`, on the reasoning that the browser
sends literal UTF-8 and the Pipe keeps it literal. Both halves are true and the conclusion was not —
the API re-serialises the body with the default escaping one hop before the Pipe. Measured: 49
folders of accented keys passed the 64 KiB cap at 64,730 bytes, cost **189,974** on the wire, and
produced a failure state **27,151** bytes over the limit. Both sides now measure the escaped form; the
cap does not move and an ASCII selection is unaffected. **The wire stays pure ASCII deliberately** —
that is what keeps the worst-case escape into the Pipe record a provable 2.0 whatever AWS's own
serialiser does.

**Two things this entry does not claim.** `requestId` was never the live hole the spec described:
`fifo._checked` refuses a derived deduplication key over 128 printable-ASCII characters before the
send, on the nine routes that make the id one. And the Pipes-record overhead reservation is
**modelled, not measured** — no captured record exists in the tree — which its declaration says so
nobody reads its passing as evidence about the real record. Detail: `spec-delivery/SPEC-229`.

## Everything unbounded on the state travels by pointer — including the definition (SPEC-161, extending SPEC-090/160)

The rule the table-share plane arrived at over three specs, stated once: **anything on the Step Functions state whose size a user controls lives in the admin bucket and rides as a key.** The object list went first (PR #256, at 95% of the 256 KB payload), the transfer manifest was born that way (SPEC-160), and SPEC-161 finishes it with the **cloned table definition** — `{admin_bucket}/table-share/{hash}/definition.json`, written by `inspect-source`, fetched by `create-table`. `tscommon.copy_plan` owns all three key layouts, so the request digest has one home.

**A cap is not an alternative to a pointer, and this is the case that shows why.** The definition was bounded inline by `SHARE_MAX_DEFINITION_BYTES` at 32 KiB, and that number was doing two incompatible jobs: keeping the Map's state safe, and deciding how wide a table a user may share. A 100-column table with column comments serialises to roughly 32 KiB — an ordinary thing to want to share, sitting exactly on the boundary. Measured: with the definition inline at cap, the guard Map's peak state reaches **~55%** of the limit; with the pointer it is ~29%. The cap could protect the payload or serve the user, not both. **`test_the_whole_map_state_stays_under_the_payload_limit` now adds an at-cap definition back to the modelled state and asserts it fails the safety bar**, so the pointer is demonstrated to be load-bearing rather than assumed to be tidy.

`SHARE_MAX_DEFINITION_BYTES` survives at **64 KiB** as an object-size sanity check, and **what sizes it is now Athena, not Step Functions**: the definition renders into one `CREATE EXTERNAL TABLE`, and Athena's query-string quota is **262,144 bytes and not adjustable**. The rendered statement can be **twice** the serialised JSON — `ddl.literal` backslash-escapes, so a `'` costs one byte in the JSON and two in the DDL — and *where* those quotes sit decides the ratio: a table property or SerDe parameter carries ~9 bytes of JSON overhead and renders at nearly the full 2x, where a column comment carries ~40 and reaches only ~1.7x. At 128 KiB the property-shaped worst case measured **99.98%** of the quota; at 64 KiB it is 50%. Do not re-read it as a state bound, and do not raise it on the strength of a comment-shaped measurement.

**Three keys, two disciplines, and the split is about what the content depends on.** The plan and the definition are **pure functions of the request** — the digest covers the source database and table, so two overlapping executions write byte-identical content and either object is correct for either run **— superseded in part 2026-09-15: only while the source is unchanged between the two runs' reads of it ([the group id entry](#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide)) —**. The manifest is **execution-unique**, because its lines depend on which recipients the guard Map accepted, which is time- and destination-dependent (SPEC-160's entry has the full argument). Do not "make them consistent" by giving the definition an execution segment; it would multiply objects under a lifecycle rule for no gain.

**An unreadable definition fails THAT RECIPIENT, never the request, and never renders anyway.** `definition_unreadable` is terminal for the finish Map's item, and the reason the load refuses an object with no columns rather than passing it on is specific: an empty column list renders a `CREATE EXTERNAL TABLE` that **Athena accepts**, over the recipient's freshly-copied data — a table that reports success and returns nothing.

**No IAM changed.** `CopyPlanReadWrite` already grants `PutObject`/`GetObject` on `${admin_bucket_arn}/table-share/*`, which is the whole benefit of one prefix owning every artifact — and the same property is why FR-004 was discharged by adding **no lifecycle rule**. Detail: `spec-delivery/SPEC-161`.

## Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)

A Standard workflow with no `TimeoutSeconds` runs to Step Functions' default of **one year**. That was harmless while the copy was one Lambda bounded by its own 900-second timeout; once SPEC-160 made it a Distributed Map and SPEC-161 raised the byte cap to 1 TiB, "wedged" became a state a run could sit in indefinitely.

**It is a TOP-LEVEL ASL field** — beside `StartAt`, not an argument to `aws_sfn_state_machine` and not a task field (SPEC-157 settled the same distinction for the table-builder's lock). On a Task it would bound one step, which is not what a wedged *run* needs.

**And a top-level timeout CANNOT reach `NotifyFailure`, which is the trap this entry exists to record.** The state sits in the machine looking exactly like it would. It does not: AWS documents that *"Step Functions catchers are available for Task, Parallel and Map states, but not for top-level state machine execution failures"*, and the remedy it names is *"listen for `TIMED_OUT` events from Standard workflows with an EventBridge bus"*. A top-level expiry terminates the execution outright — no state runs, no `Catch` fires. **A `TimeoutSeconds` shipped alone would therefore have bounded the run and made the sender's silence permanent instead of merely long**, which is worse than it sounds: SPEC-152's guarantee would read as satisfied by a state that could never be reached.

So the field ships **with an EventBridge rule** (`stepfunction.tf`) on `Step Functions Execution Status Change`, matching **`TIMED_OUT` only** and invoking the same `notify-failure` verb through a second door. AWS classifies Step Functions execution events as **best-effort delivery**, so this closes the hole rather than sealing it — a dropped event means the old silence for that one run. That is accepted: the alternative is polling `ListExecutions`, which is a scheduled sweep and a second moving part for a failure mode measured in runs per year. `TIMED_OUT` only is load-bearing: every whole-request failure a `Catch` takes already reaches the verb and ends at `Fail`, whose status is `FAILED`, so matching both would send a second notification for every caught failure. The two doors are disjoint by construction, not by a suppression rule.

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
> it now blanks the two LEGACY top-level token fields, because a message enqueued before the API
> stopped sending a token carries one and is exactly what this drain surfaces. It must not be
> pointed at `identity` — top-level replacement would blank the block the recipient was just read
> from. Points (3) and (4),
> and the undrained notifications DLQ, are unchanged.
>
> **Narrowed (2026-09-10):** point (3) governs the MESSAGE and still holds. The row's `payload`
> now carries the body's `requestId` and nothing else from it — see *`requestId` rides on every
> row*.

The **notifications DLQ is deliberately undrained** and is the one hole this cannot close — the drain's only delivery channel is the queue that DLQ implies is broken; the honest answer there is operator-facing. **No redrive, no replay, no CloudWatch alarms** (an alarm with no target told the user nothing — the user decision that killed SPEC-114 FR-005). **Follow-up (2026-07-22): the four SQS event-source mappings became one EventBridge scheduled sweep** (`rate(10 minutes)`) — the mappings idle-long-polled four almost-always-empty DLQs around the clock, and that was the bulk of the account's SQS request volume (it was tripping the 1M/month free tier). The handler now polls all four DLQs itself (`DLQ_ARNS`, the same ARNs as an env JSON list) and **deletes every message it reads whether or not it could notify**, so "total by construction" now means *never redeliver* rather than *safe to be redelivered* — the redelivery-loop hazard in (4) is moot because nothing redelivers (the `_guarded_notify` belt stays, so one bad message can't abort the sweep). A resource-based `lambda:AddPermission` lets the rule invoke the function, so **no invoke role** is needed (unlike EventBridge Scheduler); the execution role is unchanged (it already held the four DLQ read/delete grants the mappings polled with). Cost fell from ~10⁵–10⁶ idle receives/month to a few thousand; the price is that a dead-lettered request surfaces within one interval (~10 min) rather than seconds, immaterial for a queue nothing watches live. Detail: `spec-delivery/SPEC-126`.

## Structured-logging pipe (SPEC-127→129)

The pipe every control-plane function logs through; it carried **boundaries only** until SPEC-130 added the narrative half (next entry). `log-foundry` (pinned **exactly**, core not `[aws]`) ships in the `cpcommon` layer. `LOGS_QUEUE_URL` is **optional** (`environ.get`, never `_require`) so a function missing it logs to stdout instead of crashing a whole plane at cold start. The logs queue is **FIFO** (SPEC-129; it was standard until `log-foundry` gained the ability to set `MessageGroupId`), with `message_group_id` = the **event's own `log_id`** — **not the service**, which SPEC-129 chose and which saturated the sweep on 2026-09-10 (*The logs queue is grouped per event*, below) — with **no** content-based dedup (the library mints UUID dedup ids), and it is **swept** on a 10-min schedule, never long-polled (#270/#271). `service` = the **control plane**, and it is untrusted input on an S3 key: anything failing `^[a-z][a-z0-9-]{2,62}$` goes to `logs/_unrouted/`. Layout is `logs/service={s}/year=/month=/day=/data.jsonl` — **one appended object per service-day**, so every write is an **ETag-CAS read-modify-write** (a failed read must never overwrite a day) and the sweep role can **read** `logs/*`, reversing SPEC-127 FR-006. Delivery is put-then-delete (at-least-once; duplicates collapse on `log_id`). Partitions come from the **event's** timestamp. `logs/` is retained **forever**. `@traced` goes **outermost, above `@notifies_on_failure`**, or failed invocations close their span as `ok`. One run = **one trace** since SPEC-225 on the success path and SPEC-227 on the failure path (the API mints the traceparent and `traced` adopts it over five event shapes). The exception SPEC-227 recorded is **closed by SPEC-228 and is no longer a limit**: a failure whose error replaced the state has no traceparent on the state, and none an ASL intrinsic may reach — that much was and is true — but the forwarded envelope is on the state as `raw`, so `notify-failure` reads both the traceparent and the caller's `requestId` out of it in Python. Before that it **correlated on nothing at all**, because the seed supplies `requestId: null` on seven of the eight planes and none at all on the eighth; that was measured on archive 2026-09-09 and is what the repair was derived from. The `request_id` join stated everywhere else in this file now holds on every path. "Pre-identity" names the CATCH shape rather than the absence of an identity: all eight validators Catch `States.ALL` to that seed, so every failure raised **in the validator** lands there whatever the verb knew by then — an authorized actor's refused space included. (A failure raised downstream has its own plane's post-identity seed; archive alone has eighteen such Catches.) A refusal RETURNED as a value does not land there either: shared-spaces' `Route` sends `$.refusal` to `RefusedSeed`, one of **six** returned-refusal seeds across the fleet, and all six carry `traceparent.$`.

## Structured-logging narrative primitives & the one-door rule (SPEC-130/131)

The pipe SPEC-127/128/129 built carries **boundaries only** (entry above), and SPEC-130 opens the door to the narrative half. `cpcommon.observability` gains `info`/`warning`/`error` and `step(name)` — the module's full surface is `init`/`flush`/`traced`/`step`/`stamp`/`info`/`warning`/`error`, plus `run_traceparent` since SPEC-225 — and **no VERB imports `log_foundry`** — two test harnesses do, deliberately, since a harness that swaps the process sink must call `configure` (SPEC-224 scoped this; the absolute was never true): an emitter sits in the middle of business logic where an exception is a real failure path, so the never-raise discipline needs one door rather than thirty-four. `step` is a **thin** alias for `lf.trace` and must stay one: the library decorator is non-swallowing, and `@traced` sits **outermost above `@notifies_on_failure`**, so a step that caught anything would cost the user their failure notification. Messages are **literals**, everything variable is a field (an f-string message mints a distinct string per run and can be neither counted nor filtered). The narrative **never reaches the console**: `echo=` is prohibited repo-wide, and since SPEC-224 the prohibition is a mapping `_emit` reads rather than a grep, dropped-and-warned when passed as a field — **and it is not a silent no-op**, which this entry claimed until SPEC-224 measured it: left in place `echo` collides with the keyword `_emit` always passes and raises `TypeError` into business logic, where `fields` (reserved by the library since 1.0.0, and dropped alongside it) raises nothing and is silently reinterpreted. Both drops are asserted, warning included; the one named exposure is `init`'s `StdoutSink` fallback when `LOGS_QUEUE_URL` is unset, which **stays** because it is the cold-start safety property the module is shaped around (PR #196) and is bounded by the `logging.getLogger()` calls already putting the same keys in the same log group.

Two identity defects fixed at the same time, because instrumenting on top of them would have multiplied the damage: `traced` now passes **`name=verb`** (without it `log-foundry` falls back to `fn.__qualname__` and every root span in the fleet read `function: "handler"`) — a **discontinuity in a store retained forever, accepted without migration** since rewriting appended NDJSON would risk a day of logs to save a `WHERE` clause, with `fields.verb` populated on both sides so a query spans the cutover; and **`verb` moved from a span default to baggage** (set after `_reset_context`, which clears the whole mapping), because a span default reaches that span's own events and nothing nested — the first `step` child would have carried `request_id` but not the verb that produced it. Consumers: SPEC-131 (sweep), 132 (data-quality), 133 (DLQ drain), 134→137 (the rest of the fleet).

**SPEC-131 added an eighth name, `stamp(**fields)`** (trace baggage), because the sweep needed an invocation-scoped join key on the boundary spans and the only alternative was importing `log_foundry` at a call site — the one-door rule survives by widening the door, not by excepting it; `_stamp_verb` and `_stamp_request_id` now delegate to it. **SPEC-131's own bound is structural:** the sweep emits into the queue it drains, so its event count is O(1) in messages **and in waves**, and O(D) in the destinations it touched — a per-message emitter would give that queue a floor it could never get below, and a per-wave one makes its own volume grow with the waves a busy queue forces on it. The wave loop broke it (three events plus four per day-group every wave, defended as a ratio below one; 12,772 of the queue's 42,714 sends on the afternoon of 2026-09-10, about 640 a sweep, while it was still grouped by service) until no emitter was left inside the loop: each destination is tallied across the waves and emitted once, a sweep is **one event per destination plus three**, plus at most one per condition it reports once per sweep and a few per destination that degraded, and an empty one two; the guard is `test_a_sweep_emits_the_same_events_however_many_waves_it_takes`, which demands that no emitter is called between the sweep's first receive and its last, and the same events from two waves and from six, and proves it drove every line of the sweep bar the handler's once-per-sweep exits — so a branch added to the sweep fails it until the guard drives that branch too. A check on where an emitter is *written* was tried first and evaded five ordinary ways; a guard over spellings guards a spelling. Detail: `lambdas/info/planes/standalone.md`. Its CloudWatch calls **stay alongside** the events, uniquely for that function: the sink is SQS-only, so a sweep that cannot write to S3 cannot report through the structured store that it could not write to S3. Detail: `spec-delivery/SPEC-130`, `spec-delivery/SPEC-131`.

## The field rule — what may be logged (SPEC-130)

**The line is drawn at file contents — not at user-derived data** (user decision, 2026-07-23): `logs/` lives in the admin bucket and is read by administrators, and that destination is what makes user-derived *metadata* the right thing to log — file names, S3 keys, prefixes, **usernames** (already the S3 prefix, the principal tag and the Glue DB name, SPEC-033), database/table/**column names**, space names, counts and durations are all permitted and encouraged, because an operator debugging a failed run needs to reach the object. **Absolutely never: data from inside a file** — a cell value, a sampled row, a result set, a decoded byte range — because it can be PII, it is never needed to debug a control plane, and `logs/` is retained forever (column *names* are schema and are in; column *values* are contents and are out). **Never regardless of provenance: tokens, credentials, email addresses** — a bearer credential is not metadata, and an email is the only personal contact detail that would exist in a forever-retained prefix. There is deliberately **no runtime redaction filter** and the module docstring says so: the rule turns on *provenance*, which no filter over a field name or value shape can see, and a filter that looked like enforcement would be worse than none because it would be trusted — enforcement is review plus per-call-site criteria.

**The no-file-contents rule is about FIELDS, and `error.stack` is an ACCEPTED exemption (user decision, 2026-07-23):** `log-foundry` attaches `traceback.format_exception` to every failed span unconditionally and it walks the `__cause__` chain, so a quoted cell (a polars parse error naming the value it could not convert) reaches `error.stack` regardless — suppressing `detail` does not help (see the per-plane entry below for the `detail` audit) and neither does fixing the raise site (`raise … from exc` is what puts it there). Rather than close it (an upstream `capture_stack=False`, or a strip in the sweep), the decision is to **accept it**: `logs/` is admin-only, and a stack is diagnostic metadata an admin debugging a failed run needs, so the absolute rule binds a **field a verb chooses to emit** — not an automatic traceback. **Do not read a stack trace as licence to relax the field rule.** The characterisation test (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`) is kept as a **tripwire, not deleted**: if it starts *failing*, `log-foundry` began stripping stacks and this decision should be revisited in the open.

**The catalog surface names two values the rule reaches that nobody expects it to (SPEC-199), and it is the API that made them reachable.** Both are *arguments to an AWS call*, which is the shape a helper stamping "good telemetry" grabs first. **The SQL statement is never a field value:** user values are interpolated into SQL through `sqlLiteral`, so `WHERE name = 'O''Brien'` *is* file contents by provenance. The span carries `sql_bytes` — the length — and nothing else about the statement. **`stateChangeReason` is never a field value either:** Athena quotes the offending cell back (`Cannot cast VARCHAR 'O''Brien' to INTEGER`), so the reason is file contents by the same argument; the span carries `state` alone. Result rows and column names follow the same split as everywhere else — `row_count` and `column_count`, never the cells. **The `error.stack` exemption above does not cover any of these**, and reading it as though it did is the mistake this paragraph exists to stop: the exemption is for a traceback the library attaches automatically, and these are fields a call site *chooses* to emit, which is precisely where the absolute rule binds.

**The `error.stack` exemption covers FILE CONTENTS and not CREDENTIALS, and the API scrubs rather than exempts (SPEC-195, 2026-08-27):** the exemption above was reasoned about a polars parse error naming a cell it could not convert — diagnostic metadata an admin debugging a failed run needs, in an admin-only store. That reasoning was never applied to a bearer credential, and the API handles one on every request: a user's ID token is a credential for as long as it lives, and an admin-only store is not a safe place for a live one. Two facts were **measured rather than inherited**, and both narrow the problem. `log-foundry` exposes **no way to turn stack capture off** (re-verified against the pinned version, and asserted by a test so a release that adds one reddens rather than silently outliving this) — `config.py` offers only `max_stack_bytes`, whose validator rejects any value below 1 — so exemption is unavailable and scrubbing at the boundary is the only answer. And the exposure is **not automatic**: `format_exception` renders each frame's source line, not its locals, and PyJWT's own messages carry no token material. The live route is this repo's own code interpolating the token, or the gateway event whose headers hold it, into an exception message or a log field — so the verifier raises a **fixed literal reason code** and chains the provider exception as `__cause__`, which the API never reads. `max_stack_bytes` is set explicitly at the API and is a **ceiling, not a control**: a reader must not mistake it for the scrub. If a later `log-foundry` offers an opt-out, this is revisited — the tests are not deleted.

**SPEC-137 put EMAIL on the never list** (user decision, 2026-07-23) in the shared module docstring: a username is not sensitive here (it IS the prefix, the tag and the DB name) but an address appears nowhere else, carries no operational meaning, and would be the only personal contact detail in a forever-retained prefix. The hazard is mechanical — a Cognito trigger event carries `request.userAttributes.email`, so **never log a raw event, an attributes map, or any dict you did not build field by field**; `pre-signup` logs the DOMAIN, which is what the rule turns on and is shared by every user of that provider.

## Per-plane instrumentation rules (SPEC-132→137)

**SPEC-132** spent the primitives on all nine data-quality verbs and settled two things the remaining planes inherit. **The `detail` audit is a deliverable, not a reassurance:** every `TerminalError` raise site is read, and any whose `detail` interpolates *parsed file content* logs the reason token and the exception type only — in data-quality that is `inspect-source`'s `_probe_columns` catch-all, whose detail carries a polars parse error that **quotes the offending cell**, and the suppression is unconditional for that verb rather than a denylist of reasons the next reason gets added without. And **a contents-shaped field NAME is banned even when the value is a count** — the tripwire caught `rows=` in `assemble-report` on its first run, so a row count is `row_count`; a field whose safety needs an argument is one whose name should say so instead. Failures are narrated **once per verb**, not per raise site.

**SPEC-133** took it to `control-plane-dlq-drain` (`service="dlq-drain"` — not a control plane, since it spans all four and is nobody's verb) and settled two rules the rollout inherits. **`request_id` is a FIELD wherever one invocation handles many requests, never baggage:** `_reset_context()` runs once per invocation, so on a function draining up to 400 messages, baggage would leak one request's id onto the next — the fabricated correlation key SPEC-128 FR-002 forbids. **And one event per item is right or wrong depending on which queue you emit INTO:** the sweep emits into the queue it drains, so per-message events give that queue an undrainable floor; the drain emits to the logs queue and drains the request DLQs, so per-message is correct there. The dead-lettered body is a **permanent forensic record** — redacted (every known token field), size-capped, and ONE serialized field, never re-parsed into fields or a body could shadow `request_id`/`verb`/`service`.

**SPEC-134** promoted the per-plane coverage guard to a **fleet-wide harness** in `control-plane-common`: registering a plane is one `Plane()` descriptor (its glob, service name, expected verb count as a LITERAL so a short enumeration fails rather than passing vacuously, and its decorator expectation), and a verb module is found by **defining a top-level `handler`** rather than by any filename convention. It also settled that **the decorator rule is per-plane and DECLARED**: shared-space verbs notify from inside the handler, so `@traced` is asserted to be their ONLY decorator — adding `notifies_on_failure` there later fails until someone establishes the ordering. And **per-item events are permitted where the bound is STRUCTURAL**: the roster fan-out emits per member because membership is capped at ten Cognito slots, which is the same rule as SPEC-131/133, not an exception to it.

**SPEC-135→137 finished the fleet.** 135 logs Athena's `StateChangeReason` **verbatim** alongside the stable token — that raw text is what would have named the missing `CREATE_TABLE` grant, and a token cannot carry a diagnosis — and moved the DDL poll's transition-only narrative into **`cpcommon.athena`**, since the loop is shared. 137's email decision lives in the field-rule entry above; 137 also verified empirically that **`cpcommon.observability` imports and emits with ZERO env vars** (`cpcommon/__init__.py` has no imports, `clients` lazy-imports boto3), which is what makes the layer safe to attach to functions that lack the six `config._require` variables — one `from cpcommon import config` added to `__init__.py` would arm PR #196's bomb for them. Detail: `spec-delivery/SPEC-132`, `spec-delivery/SPEC-133`.

## The log-foundry pin, and what a library upgrade owes the code written around it (SPEC-224)

The fleet runs **`log-foundry==1.0.0`**, pinned exactly and core-only, for the reasons the pin's own comment gives. What this entry records is not the bump but its **shape**, because two of the three changes that reached this repo were things the codebase had built *around* the old version, and both were invisible to a green suite.

**A capability the library gains retires the workaround, and the workaround does not retire itself.** `configure(sink=…)` now drains, closes and re-points delivery; before, it leaked to the sink it replaced, which is why two harnesses retired the worker by hand. That reach could not merely be left alone: the private name behind it no longer exists, so it had degraded to a **silent no-op behind a `getattr` default** — reading as load-bearing while doing nothing. A second reach was worse than redundant: the library now holds a live sink beside the stored config, so `conftest.py`'s `_config` restore left it **reporting one sink while delivering to another**, on the span path only (the orphan path agrees even when it is broken, so an orphan-path probe passes vacuously).

**A prohibited-name list must be READ by the thing that prohibits.** `_emit` refuses `echo` and `fields`, and they are refused for **different reasons**: an un-dropped `echo` collides with the keyword `_emit` always passes and raises `TypeError` into business logic, while an un-dropped `fields` is the library's own parameter and raises **nothing** — the mapping is unpacked over the event and the author's field silently vanishes. The first version of this change defined `PROHIBITED_FIELDS` and hard-coded both names beside it, so emptying it changed nothing and extending it dropped nothing. The constant is now read, and a test plants a third name.

**Three standing rules this settled.** No module outside `cpcommon/observability.py` and the two named test harnesses reaches an underscore-prefixed `log_foundry` name — held by a guard that resolves **import aliases**, because `import log_foundry as lf; lf._lifecycle` is the spelling this repo actually uses and renders with neither the package name nor a recognisable prefix in it. No `@traced`/`@step` function may be a **generator**: the library refuses one at decoration, which for this fleet is a cold start that never completes. And the "no way to turn stack capture off" claim three register entries lean on is **asserted by a test against the installed version**, so a release that adds an opt-out reddens rather than silently outliving the decision — the claim itself is unchanged and still true.

**A version-anchored claim rots differently from a wrong one, and the two need different repairs.** Of five claims corrected here, **two** were true of the previous pin and false of this one, **one was never true** (the one-door absolute above), and **two are still true and were merely dated to a superseded version** — including the stack-capture claim, which is unchanged and now asserted by a test. Only the first kind is a falsification; and the two dispositions that predate this pin are now stated **version-free**, since naming their release would leave a superseded version in the one block a sweep exists to clear. Full reasoning and the measurements: `spec-delivery/SPEC-224`.

## Where a child span may go, and the four places it may not (SPEC-226)

`step(name)` has existed since SPEC-130; seven planes had none of it. What this settled is not that they now do — it is **where a step may go**, because a step is two events and every event is an SQS message and a line in a day object the sweep rewrites in full, so placement is a volume decision rather than a taste one. **The four prohibitions and their mechanisms live once, in `lambdas/info/shared-layer.md` (`cpcommon/observability.py`), and are not restated here.** Recorded here is what a later spec must not re-litigate.

**The premise a reviewer destroyed.** The first design claimed the shared `cpcommon` layer bought child spans for all seven planes at once. Built, that was false: **five of the eight shared functions it named are called inside loops**, so stepping them is the per-item instrumentation the design forbids. What survives shared is the **transfer trio** — `copy_batch`, `write_manifest`, `read_failed_items` — reaching four planes; shared-space, results-conversion and table-builder get theirs at the bounded call site in their own code, **the loop and never its body**. Two of the trio are bounded at **most** once, not once, so a test asserting exactly one call fails on an empty transfer.

**A per-verb check is not a fleet-wide claim, and the difference cost a name.** Three span names were corrected by checking each against *its own* verb's root span; a fourth, `write-manifest`, collided with a **different** verb's, which that check cannot see. The guard sweeps every step name against every verb name. It began carrying that one pre-existing collision as a named item with a companion staleness test; the collision was then **renamed away** — data-quality's manifest step is `write-inspection-manifest`, leaving `write-manifest` to the archive verb — so the guard now excuses nothing and both the item and its companion are gone. **Rename the STEP, not the verb, and the reason is not which is older** (the step predates that verb by three weeks): a control-plane verb's root span name is its Lambda's identity in several places at once — the directory's suffix, which every verb in a `<plane>-<verb>/` directory matches, and for this one the `locals.tf` map key a test reads back, the state machine's wiring and `moved.tf`. **A step name is the cheap side only when nothing reads it, which is not a property of steps** — data-quality's are read by no code, no IaC and no test, so this was a one-line move, while all three shared transfer steps are held by literal in `test_observability_transfer.py`, and `copy-batch` again in `test_child_spans_per_plane.py` and in the live-check guide. Check which kind you have before assuming the step is the side that moves.

**A guard over decorators must resolve the name a decorator is BOUND to.** Matching the rendered text `observability.step` was defeated twice — by `from cpcommon.observability import step`, and then, after that was closed, by a plain `import cpcommon.observability`, which binds the **root package** so the usable spelling is the full dotted path. Both put per-item instrumentation on a forbidden function with the whole suite green. This generalises past spans: a guard that matches how a name is *written* is guarding a spelling, not a rule.

**A threshold that reads like a fence may be a detector.** FR-005's budget rests on `log_sweep.LARGE_OBJECT_WARN_BYTES`, which is sized to fire *long before* anything binds. That makes it a conservative basis for a budget and **not** the day-object ceiling; the ceiling's real value needs the sweep's peak-resident multiple, which is unmeasured. Refusing to derive a budget at all was the first answer and the wrong one — erring safe is how a budget is stated. The drain that follows from it repairs nothing that pre-existed — removing it reddens only the tests written for the drain itself — so it is a forward guard rather than a fix. Detail, the rejected rate-free alternative, and the delivery-timing consequence: `spec-delivery/SPEC-226`.

## The failure path joins the trace, including where ASL cannot reach the value (SPEC-227, SPEC-228)

SPEC-225 put a run's **success** path into one trace. The half an operator actually opens after an
incident is the other one: `notify-failure` is a **separate invocation**, reached from
`RecordFailure` through `"Payload.$": "$"`, so unless every state between the failure and the
notification names the traceparent, that span belongs to a trace of its own. Twenty-nine states now
carry it — 13 post-identity seeds and 8 `RecordFailure` states read `$.traceparent`, 8 pre-identity
seeds supply a literal `null`.

**The limit was real and was not a shortcut, and the obvious repair does not work.** A seed
reading `$$.Execution.Input` cannot get at the value: with no `input_template` on any Pipe that
path is the raw SQS batch, the traceparent is inside `[0].body` as a JSON string, and extracting it
needs `States.StringToJson` — banned in ANY intrinsic-evaluating field on any state, not only on
`$.error.Cause`, for the same uncatchable `States.Runtime`. Independently,
`observability._shape_values` walked four inbound shapes — top level, the SQS envelope,
`BatchInput` and `request` — but never `raw`. **That second half was the repair rather than the
reason, and SPEC-228 took it:** the envelope does not need parsing in ASL at all, because it is
already on the state. The extractor gained `raw` as a fifth shape, every `RecordFailure` carries
`$$.Execution.Input`, and the failure that replaced the state now joins the run's trace AND
recovers the caller's request id. The ASL half above stands unchanged and is still why the
machines are shaped this way.

**The guard had to be widened before anything was threaded through it, and that ordering was the
point.** Recognition of a "failure seed" was structural (`Parameters["error.$"]`), which missed
**nine** states that replace the state with a literal `error` object. Proved rather than argued: the
obvious edit — the traceparent onto archive's `RecordFailure` and the two seeds the guard could
see — left the whole suite green while six archive failure paths would have hit an absent key inside
a `Pass`. Recognition is now the **union** of the structural test and a graph test (every reachable
terminal is a `Fail`), because the graph half alone loses the three nested seeds whose
`ItemProcessor` contains no `Fail`. "Terminal" means **a state that hands control nowhere**; under
the other reading an `ItemProcessor` has none, `all([])` is true, and the sweep selects success
leaves.

**The cross-check's own limit is the interesting part.** Driving a verb answers the question only
for a verb that **builds** its return. One returning `{**event, …}` inherits its key set from its
input, so driving it with a hand-built mid-chain state compares the fixture with itself and agrees
with any state at all. Seven of eleven pairs qualify; for three of the other four a faithful drive
is impossible rather than expensive, because a Distributed Map sits in the chain and the state after
it comes from a Map Run export no drive can produce. Exclusions are recorded, and a test reads each
excluded verb's source to confirm it really does echo — so the escape hatch cannot be used to
silence a failing pair.

**And the sweep's own producer guard is a DETECTOR, which is worth knowing before anyone leans on
it.** Whether a verb's return still carries its input's keys is not decidable from source: five
drafts of the classifier were each defeated — a bare `return <name>`, a `**<name>` spread, an
`event`-anchored version, `dict(event)` then `.pop`, and a genuine echo trimmed afterwards by a
helper. Binding to the handler's return and failing closed was measured and rejected — it flags
most of the fleet's verb directories, because most verbs build their return rather than echoing
it. What it catches is the shapes that occur, plus a fleet-wide tripwire on the one shape
that names nothing — a verb that reshapes a mapping. Production correctness today rests on the
traced analysis rather than on the test — but that analysis was a one-time review artifact over the
eight graphs as they stood, so the day a ninth producer lands the detector is the only live thing
left. Its job is to make the next change to one of those verbs loud; weakening it removes the only
standing check.

Do **NOT** add a second copy of a plane's fixture to drive its verb: import the plane's own suite.
Do **NOT** hold a state's reads to a verb that echoes its event — the answer is your fixture.
Do **NOT** glob `lambdas/*/*.py` for a fleet-wide source sweep — it sees the handler modules only,
and misses the `*-common` packages, the API tree and the files at `lambdas/` top level. A key
dropped in any of them is invisible to it.

Detail, the corrected populations, and the residual first-segment gap: `spec-delivery/SPEC-227`.

## A run is ONE trace on the success path, and the extractor is a security boundary (SPEC-225)

The traceparent is minted at the **API** — the one place a run begins — written into the message
by `enqueue.build_message`, and adopted by `traced` before the span opens, so a verb's root span
parents to the API's. `request_id` **stays**: it is the join key for anything outside the trace — **including the failure path whose error replaced the state, where the seed nulls it and the notifier recovers the caller's own id from the forwarded envelope instead** (the SPEC-127→129 entry above carries the measurement of what that path looked like before),
and table-share carries none at all.

**Five event shapes**: the state payload, the EventBridge Pipe envelope, a Distributed Map's
`ItemBatcher.BatchInput`, an inline Map's `request` block, and the forwarded envelope a failure
terminal carries on the state as `raw`. The Map ones carried no correlation value of any kind
before SPEC-225, which is why nine Map-child verbs could not be joined to their own run; the fifth
is the failure path's, and it is a walk over the SAME envelope the Pipe branch reads rather than a
second parser, so the list-only narrowing below is enforced once.

**The shape list is a security boundary, not a convenience.** The request-id walk
(`request_id_of`) used to fall back to parsing a bare dict's `body`, and for an API Gateway payload-2.0 request that `body` is
**the caller's own HTTP body** — so a caller could name this service's correlation key. Latent for
the request id, because the router overwrites it with the gateway's; **not** latent once a
traceparent travels the same walk, since nothing overwrites an adopted trace. The body branch is
narrowed to a **list**, which closes both.

Three mechanisms that each look like a detail:

- **Adoption comes AFTER the per-invocation reset.** `reset_context` clears an adopted context as
  well as baggage (SPEC-224), so adopting first means the reset erases it. The ordering is the
  whole reason this spec was sequenced behind that one.
- **`run_traceparent()` keeps the adopted value VERBATIM**, in a `ContextVar` of this module's own.
  The library's accessor returns `(trace_id, parent_span_id)` with version and flags discarded, so
  a rebuilt string re-emits an inbound unsampled `-00` as `-01` — a sampling decision silently
  reversed on the way through every verb.
- **A Distributed Map's child cannot see the parent state**, and all six read a JSONL manifest
  through `ItemReader` with no `ItemSelector`. `ItemBatcher.BatchInput` is the only place a
  per-run value can travel; the manifest would repeat it on every line of a dataset holding tens
  of thousands. The pair is **per-plane** — table-share's state has no `requestId`, and an
  unconditional one there is an uncatchable `States.Runtime` on every share.

Rejected: threading it through `ItemSelector` (none of the six has one, and adding one copies the
whole parent state into every item); writing it into the manifest (repeats per line); and reading
it from the traceparent header (the planes are entered by SQS, not HTTP).

**What is owed**: a real run's records carrying one `trace_id`, and — falling out of the same
reading, since archive's Maps carry the block — an execution proving `BatchInput` reaches an
`ItemReader`-fed Map's child. AWS documents that pairing nowhere and `test-state` refuses a Map's
child outright. Partly discharged: the service's own definition validator accepts all eight
templates and refuses a `BatchInputTypo` as unsupported, so the field is real and a red first
apply is ruled out.
Detail: `spec-delivery/SPEC-225`.

## No ASL state decodes an error Cause (PR #252, control-plane-wide)

`States.StringToJson($.error.Cause)` raises `States.Runtime`, which is **neither retriable nor catchable anywhere** — not even by a `Catch` on the same state. The `ParseError` `Pass` states that did this killed executions *before* the recorded-failure/notify states on 3 of 4 real error shapes (`States.Timeout`, `States.DataLimitExceeded`, `Lambda.Unknown` — verified live with `TestState`, which injects the shape; a real `States.DataLimitExceeded` is never caught, so it never reached a `ParseError` state at all). Terminal states now carry the **raw `$.error` `{Error, Cause}`**; `cpcommon.errors.failure_reason` decodes it in Python. Enforced by `lambdas/control-plane-common/test_state_machines_cpcommon.py`. Related trap: a `Pass` state's JSONPath hard-fails on an **absent key** (a null *value* is fine), so anything a terminal `Pass` names must be seeded on every path — now **enforced by a test** (SPEC-114): every `Pass` reachable from a failure seed may read only keys that seed supplies. It has caught this arc twice (`$.location`, SPEC-112; `$.reportKey`, SPEC-114).

## Notifications (SPEC-058→061)

Per-user inbox at `{username}/user_settings/notifications.json` (array of `{id,message,read,timestamp}` — plus an **optional `link`**, SPEC-113 FR-008: an in-app path the message renders as, gated at render by `isSafeInAppPath` so it can never become an open redirect; absent = plain text, which is every pre-113 producer). **Single-writer:** all mutations (system `create` + user `markRead`/`markAllRead` — **no delete**) go through a **dedicated FIFO SQS queue that triggers the writer Lambda directly** (SQS event-source mapping, batch size 1 — **no Pipe, no Step Function**); per-user ordering via `MessageGroupId` = username. The browser only **reads** the file (+ a **60s background poll** for the unread icon) and enqueues ~~(`sqs:SendMessage`)~~ **— superseded by SPEC-200:** its two user actions through the API's `notifications.enqueue`, holding no grant on the queue. Anti-spoofing = ~~user-action messages carry the Cognito **ID token**, writer derives `username` from the verified claim~~ **— superseded by SPEC-201:** a user action carries the API's `identity` block, read through `cpcommon.actor`, and any body username is ignored (`create` = trusted-producer-only — **enforced since SPEC-206** by the writer refusing a `create` whose SQS-stamped `SenderId` names the portal role; ~~the grant itself is unconditioned and cannot be otherwise, since no SQS condition key reaches a message body~~ **— superseded by SPEC-200:** the portal role holds no grant on the queue at all). UI = header bell **linking to a `/notifications` page** (not a drawer, not a tab), **10/page**, mark-read/mark-all only. First `create` producer = the **shared-workspace control plane** (SPEC-061; seven lifecycle events, incl. delete fanning out to all members), granted `sqs:SendMessage` on the queue. (**058 write pipeline shipped** — `infra/modules/notifications/` + `lambdas/notifications-writer/`; **059 browser data layer done** — `features/notifications/` read service + `useNotifications` + prefetch; **060 UI done** — header `NotificationsBell` link + `/notifications` page (10/page, mark-read/all, optimistic + Toast); **061 done** — the 062 verb Lambdas emit `create` inline via `notify.emit_notification` (orchestrator role gains `sqs:SendMessage` to the notifications queue ARN only; `NOTIFICATIONS_QUEUE_URL` env), best-effort.)

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

**One error in that list is not closed by it.** `States.DataLimitExceeded` is caught only by a
catcher that names it, and none in the fleet does, so it still ends a run FAILED without reaching
`NotifyFailure`; so does `States.Runtime`, which `States.ALL` never catches. No event rule matches
FAILED. The machines are built so neither is raised, which is why the data-quality footer carries
no "always".

**A fifth plane cannot ship without it.** `test_state_machines_cpcommon.py` enumerates every
`state-machine.asl.json.tftpl` under `infra/modules/` and asserts each has a `NotifyFailure` Task with
a `States.ALL` Catch, plus that its `RecordFailure` copies `$.error` **whole**. The exemption list is
an empty dict — an entry is a decision to leave users in the dark, not a formality. The second
assertion is not redundant with the throwing-intrinsic guard: a plane could satisfy that one perfectly
by copying `$.error.Error` alone, and every message would silently degrade to the generic.

**The duplicate-suppression mechanism differs per plane, and the difference is forced, not stylistic.**
This state sits on *every* failure path, because the paths where no verb ran cannot be selected for in
ASL — so an ordinary failure would otherwise notify twice.

- **Six of the eight planes** suppress in Python via `_verb_already_notified`, on **one name**:
  `Error == "TerminalError"` — table-builder and table-share, which this clause used to name
  alone, plus archive, file-ops, file-send and results-conversion. `data-quality` and
  `shared-spaces` carry none at all. **Counted 2026-09-09** — this clause named two of the six
  and had not been widened since it was written against four planes. The name is the only
  *positive* evidence available — a verb raised it
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

> **No longer empty.** The table now maps the class names of the plane's own terminal exceptions —
> `MembershipRefused`'s subclasses among them — to sentences a user can act on. For any exception
> but a `TerminalError`, `failure_reason` returns the engine's `Error` field, which is the raised
> class's name, so the keys are class names verbatim and a newly raised refusal renders the generic
> clause until its class is registered.

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
docstring and still holds **— superseded in part 2026-09-15: only while the source is unchanged
between the two listings, the residual that docstring itself names; if it changes, the two runs
copy different sets into one location ([the group id entry](#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide)) —**. It does **not** carry to the manifest: its lines depend on which
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
**after the deletion**, and that error escapes every `Catch` here (`States.ALL` does not match it and
none names it) — so the user would be told nothing at all about an operation that had already moved
their data.

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
beyond the spec's own acceptance criteria and was built deliberately. The one refusal that writes no
row at all is a reused request id: the run holding the id reports under it, and its outcome row is the
one the card should settle on ([told to nobody](#a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is-the-one-that-reports-data-quality-file-operations-archive)).

**Built into the emitters, it still never reached a failure row, and why is the lesson.** The
emitters forward whatever id their event names, and their test handed them one. The validator
builds that event by hand and left the id out, so every validate-stage refusal landed with
`payload: null` in production, and the failure terminal sent no payload on either of its doors.
Now the validator names the id, and the terminal reads it through
`observability.request_id_of`, which finds it in the forwarded request wherever the seed nulled it.
The tests drive the validator's handler and the terminal's doors, because an emitter's own test
cannot see what its caller leaves out. Results-conversion had the same two gaps: its terminal sent
no payload, and its validator named the id only once the contract passed. Both took the same fix,
though no reader tracks a conversion in flight yet: every row the plane's own Lambdas write now
carries the id, and the first reader built would otherwise miss exactly the failures nobody
exercises.

**The shared DLQ drain writes the id too, on every plane it drains whose request names one** —
all but table-share, which has no request id. That closed the last row that settled nothing: a
dead-lettered file operation held its card, and the space's submit gate, until the card's
three-hour expiry unless the user dismissed it. The drain predates the payload field, and adding
one took an argument, because the drain's rule is that no value from the untrusted body reaches
the message and this takes one into the row. The rule still governs the message. The id is
admitted to the payload, alone, on three grounds. The recipient is the actor the API stamped, and
a delegated one is refused, so the id lands only in the inbox of the caller who chose it. The
other two are particular to the id: only the API writes the block a recipient is read from, and
it also made the id the message's deduplication key, so SQS has already held it to 128 printable
ASCII characters — the operator reader's `requestId` is not its dedup key, but its messages carry
no block and notify nobody; and no reader renders the id as text — the browser keeps a payload
only when its id cannot change a URL, and matches on it. A `{requestId}`-only row reads to the
file-ops card as a refusal, the word it uses for every run that failed before an outcome, and the
notification beside it says the request never started.

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
> whose SQS-stamped `SenderId` names the portal role. ~~The grant is still unconditioned — that part
> stays true, and is why the control is a runtime one.~~ **— superseded by SPEC-200:** the grant is
> gone, so the portal role cannot send to this queue at all, and the runtime check stays behind that.
> See the SPEC-206 entry at the end.

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
for the person it is telling **— and since SPEC-201,** because a plane writes a `create` itself, not
through the API, so it carries no `identity` block, and the person it tells need not be the caller
it acted for. **The IAM policy never implemented it.** The portal role's
`sqs:SendMessage` on the notifications queue was unconditioned, so any signed-in user could enqueue a
`create` naming anybody and saying anything, including a clickable in-app link. The comment above that
grant asserted the opposite, which is the dangerous combination: a reader checking the IaC was told the
question had been answered.

**IAM cannot express this rule at all, and that is the argument — not a preference for runtime checks.**
No SQS condition key reaches a field inside a message body, so a queue or identity policy could only
deny the portal role `sqs:SendMessage` outright: the same principal on the same action that `markRead`
and `markAllRead` ~~need~~ **— superseded by SPEC-200:** needed then; they reach the queue through the
API now. There is no policy that permits two of the three actions. So the boundary is the
`SenderId` SQS stamps on every message — a message *system* attribute the service sets and a
`SendMessage` cannot — compared on the **role-id half**, the substring before the first `:`. Not
equality against the whole value (which never matches, and a control that never matches reads exactly
like one that works) and not `startswith` (which would refuse an unrelated role whose unique ID merely
shares an opening). The session-name half is never examined: ~~Cognito's enhanced flow does not document
what it puts there~~ **— superseded by SPEC-202:** the Identity Pool is gone, and the API assumes the
portal role with the username verbatim as its session name, which says which user it is and nothing
about whether the role may send.

**The rule is a DENY of one principal, not an ALLOW of the rest.** ~~The grant is held by every
control-plane execution role, the DLQ drain and the portal role — and exactly one of them is
user-reachable, which is what makes a single-principal refusal complete rather than partial.~~
**— superseded by SPEC-200:** the portal role no longer holds the grant. The user-reachable sender
is now the API's execution role, and its `notifications.enqueue` request model accepts only
`markRead` and `markAllRead`, so a user's `create` is refused at the API (400) before the queue. The
count of the grant's holders is deliberately not written here: it moved with the eighth plane, and it will move again. An allow-list would be a
hand-maintained list of role IDs that fails closed on the day a plane is added: that plane's
notifications would stop, drop or dead-letter unnoticed and nobody would connect the two. One
environment variable beats eight, and the deny direction fails open only toward principals that require
an explicit IAM change to exist.

**A refusal LOGS AND DROPS; it does not raise.** Raising would cost three invocations and one permanent
dead-letter message per forged request, on the queue whose DLQ SPEC-126 deliberately leaves undrained
and which is this plane's only operator-facing signal — handing ~~every signed-in user~~ **— superseded
by SPEC-200:** whoever could send as the portal role, which no signed-in user now can, a way to drown it.
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
is the **interim** fix: ~~Arc B removes the browser's grant (SPEC-200) and after SPEC-196 the denied
principal becomes a *service* principal, harmless because every `create` is emitted by execution roles.
The check stays regardless; that removal is eleven specs out and reversible.~~ **— superseded by
SPEC-200:** the browser's grant is gone, and the check stays behind that. It still names only the
portal role, so a `create` from the API's execution role would pass it — the API's route refusing
the action is the fence against that sender. Detail:
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
statement naming this queue and never did. On the user plane it would have to, ~~and then any
signed-in caller could write a feedback record under whatever username it chose, because no SQS
condition key reaches a field inside a message body~~ **— superseded since SPEC-202 retired the
Identity Pool:** no caller holds portal-role credentials, so the grant would instead ride on every
session the API mints for every user, and no SQS condition key reaches a field inside a message
body to tie a record to its sender. The request type declares no username field,
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
peak ~~measured on the fleet image at 23–32x the input CSV~~ — **superseded by SPEC-230**: the peak
is set per CELL, not per byte, and that figure was one shape's; see *Excel is bounded by cells*
below. One cap for all three is dishonest in
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

## The destination prefix is relative, and the doubling it invites is refused by nothing (SPEC-223)

`ConversionDestination.prefix` is **relative to the space root** — `rccommon.paths.destination_key`
builds `{root}{prefix}{filename}` — while the browser's `DestinationPicker` deals in full in-space
prefixes rooted at `alice/`. Handing one straight to the plane writes `alice/alice/reports/q1.parquet`,
and **no gate catches it**: `cpcommon.paths.assert_inside_root` proves the key sits inside the root,
which a doubled root does, and the write then succeeds into a folder the user never chose.

The browser slices the root off, and **derives** it from the very string being sliced rather than
looking it up in its list of spaces. That is the part worth keeping: the first revision did look it
up, with `?? ''` when the destination was not found, and `startsWith('')` is universally true — so
the fallback re-created the exact bug the slice existed to prevent, through the one branch no test
covered. Derived, `spaceFor(...).name` *is* the prefix's first segment, so the slice is total and
there is no branch to get wrong. A guard around it was tried and deleted: a review planted its
removal and the whole suite stayed green, because no reachable input can fail it.

**A fixture set that is all personal cannot see any of this.** The read space and the write space
coincide for a personal destination, and so do the absolute and relative prefixes' first segments —
the conversion tests use a shared-space destination for that reason, and the live check in
`e2e.md` §4.3 is the one row worth running even if no other is.

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

## Excel is bounded by cells, because the converter's memory is spent per cell (SPEC-230)

**The byte cap admitted a result the converter could not hold, and every up-front check agreed.**
A 1,048,575 × 15 one-character result — 62,914,590 bytes, under the 64 MB cap and exactly at
Excel's row ceiling — ran the converter for its full ten minutes at its full 3,008 MB, and the user
was told "something went wrong". The cap had been derived per CSV BYTE from one wide shape, and the
offline time check that stood behind it measured a wide shape too, so it passed. The Excel path's
peak is set by CELLS: polars hands xlsxwriter a Python copy of every cell and xlsxwriter stores each
again, at no less than about 240 bytes a cell whatever it holds — more for long text or a narrow
result — while a CSV cell can be one byte. A byte cap
safe for the worst shape would be about 8 MB.

**Cells, not bytes, and not a streaming writer — the owner's call.** xlsxwriter refuses
`add_table()` in `constant_memory` mode, and polars' `write_excel` always builds a table from
`df.rows()`, so streaming means a hand-written writer that loses the Excel table — and still needs
a cell cap, because time is per cell as well. It is the follow-up if the cap proves too small.

**The rows are counted in the converter, not in describe-results.** The only cheap source up front
is Athena's runtime statistics, which the API reference says may not be returned and are omitted
under Lake Formation row filters, and the only fallback for a missing count is the byte cap this
replaced. The converter counts through ONE column with the real CSV reader, and both Excel
refusals are decided from that before the frame exists, the row ceiling first — and asked again of
the frame's height once it is built. **Not `pl.len()`**: polars' fast count projects nothing and
tracks quotes chunk by chunk, so across threads it miscounts a quoted newline, and a review showed
it admitting a result over Excel's ceiling whose rows xlsxwriter then dropped, reported as saved.
Each refusal names its code where it is raised, because the plane's vocabulary sweep reads a
literal first argument.

**The cap is derived from a measured model held to a corpus, and four things were learned
measuring it.** Units: Lambda's MB is MiB, and one anchor subtracted a decimal figure from a binary
one, which only a review caught. The anchor: the production run it rests on was rebuilt from
Athena's own history, to the byte, rather than approximated by a shape that looked similar. The
cgroup slope moves by several percent run to run, so every constant is rounded up above the worst
run and the 15% reserve stays. And one anchor does not transfer: the live conversion at the cap
came in well above both the band predicted from the anchor and the corpus guard's own figure, and
inside the model, so a re-derivation is validated by a live conversion as the plane page's Traps
say, not by the anchor or by a green guard. The guard scales every measured shape to
the largest input the caps admit, through the production predicate; under the byte cap alone the
production shape fails it.

**An Excel conversion that runs out of time or memory is named**, because neither can raise and
the notifier otherwise words the Lambda's error as the fallback. The streamed formats keep the
fallback — pointing a Parquet request at Parquet would be wrong.

## The logs queue is grouped per event, because a FIFO group is the sweep's ceiling (2026-09-11)

**A FIFO message group gives up at most ten messages until they are deleted, and the sweep may
delete only once the append is durable — so each group drains ten per wave, whatever `MAX_WAVES`
says.** SPEC-129 grouped the logs queue by **service**, overriding `log-foundry`'s per-trace
default on the premise that "a single-consumer sweep cannot use [parallel delivery] anyway". The
premise was false: one receive batch spans groups, and the sweep's receive loop takes up to
`MAX_MESSAGES` a wave across them. So the real ceiling was ten per service per wave — 500 a tick,
3,000 an hour — and on 2026-09-10 one working session's `service=api` produced 10,371 events in its
busiest hour. The API partition fell four hours behind while every sweep stopped on its wave cap
having used 22–50 s of its 300 s timeout, and nothing alarmed.

**The sweep also fed its own backlog, and the convergence argument could not see it.** Each wave
put three events plus four per day-group into the `observability` group — measured 11.2 a wave
with two day-groups — against a drain of ten, so its own group grew whenever another was behind.
The recorded proof of convergence was a ratio of events to messages below one across the queue
(0.58), which guaranteed nothing, because the drain is per group. Grouping per event ends the
pile-up and not the volume, which ended when the emitters left the wave loop (the SPEC-130/131
entry above).

**Raising `MAX_WAVES` or the cadence could not fix it**, which is why neither was the change. A
day-object rewrite costs ~123 ms + 22 ms per MB, so a wave slows as the day grows: ~220 waves fit
in the timeout at that day's sizes and ~135 at 32 MB — 13,200 and 8,200 an hour per service, the
second below one session's peak. A faster schedule buys at most 1.5x, erodes the same way, and
reverses the 10-minute decision. **Grouped per event** (`log_id`, which is also the dedup id), no
group holds a second message, a wave takes up to 1,000 from any mix of services for about the same
rewrites as a wave of twenty, and the sweep's own output drains alongside everything else.
`MAX_WAVES = 50` stands. The first full wave in production took about 2.5 s for 1,000 messages,
so about 95 fit in the 240 s after the reserve. The wave cap binds first, at 50,000 a tick, against
a measured worst tick of 6,594 — a pre-deploy estimate of 5–7 s had put the cap where the reserve
binds, and the run corrected it. What is given up is delivery order, which no code
reads — the sweep partitions by each event's own timestamp — and one operator inference with it: a
partition's newest record no longer proves the older ones have landed, so while any backlog exists
the queue's age is the only completeness check.

**Do NOT group by trace**, `log-foundry`'s default: a large run's trace, and the sweep's own (one
per sweep), would still each be a ten-a-wave group. **A caught-up sweep finishes on the first wave
of arrivals alone**: during an active session each wave finds what arrived during the last, so a
sweep that waited for an empty receive would run to its wave cap over a drained queue for as long
as arrivals kept landing in every wave — reasoned, not observed: in its first two days grouped per
event every sweep finished in one to three waves with no stop reason (`docs/testing/sessions.md`,
2026-09-13), so the finish is a bound
rather than a response to anything seen. It reads each message's `SentTimestamp` and finishes, as
a normal sweep, after a wave whose every message was stamped at or after the sweep's start and
whose receive ended on an empty round rather than a cap. An undated message and a capped receive
both mean run on, because stopping early is the costly direction and SQS does not order messages
across groups. The backlog signal is still the `logs-backlog` alarm on the age of the queue's
oldest message, which has **no action by decision** — its state is read in the console and by a
session's `describe-alarms`. Sizing evidence: `lambdas/info/planes/standalone.md`.

## The notification sender bounds every dedup id, by digest rather than by dropping it (control-plane-wide)

Every `emit_notification` caller that passes a dedup id composes it from the request id —
`{requestId}:{step}` through `cpcommon.notify.dedup_id`, `{requestId}:{tag}:{recipient}` in the
shared-space verbs, `dlq:{requestId}` in the DLQ drain — and the API admits a caller's id at up to
128 characters, which is the queue's whole limit on a key. Anything added carried a long id past it:
SQS refused the send, `emit_notification` logged and swallowed the refusal, and the notification was
lost, success and failure alike, with nothing going red. Portal-minted UUIDs never come close, so
only a direct API caller could hit it, but the loss was not only their own. The shared-space verbs
key what they send the member removed, the member added, the new owner and every member of a deleted
space on the caller's id, so an owner choosing a long id could do each of those without the people
affected hearing of it. Length was not the only trigger either: `{requestId}:add-unknown:{member}`
carries a member name the caller typed, which nothing server-side holds to ASCII, so a short id
beside a name like `josé` was refused too.

**The bound sits in the sender, not in each composition**, because the compositions are an open
population: fixing the sites that exist leaves the next one unfixed. The member-name case was found
only after the bound was in place, and the bound had already closed it. `emit_notification` sends a
key the queue accepts as it is and any other as its SHA-256, so every valid key is byte-identical to
before and nothing changes for an id the portal mints.

**A digest, never None.** None would hand the send to the queue's content-based deduplication, which
collapses only byte-identical bodies, so two emits a plane keys alike on purpose — data-quality's two
reports of one failure — would collapse only if they were also worded alike. The same key always
digests to the same value, so every collapse a producer chose survives the bound.

## A group id orders the STARTS, not the runs, and what overlap costs on each plane (control-plane-wide)

Found 2026-09-15, auditing every plane's prose once the archive plane's claim that its group ids
serialize runs turned out false. Six more planes said the same thing of their own: shared spaces,
table builder, table share, file send, data quality and results conversion.

**The mechanism.** Every Pipe starts its Standard machine `FIRE_AND_FORGET`, the only mode AWS allows
a Standard workflow, and the message leaves the queue once `StartExecution` returns, after which
the Pipe sends the group's next message. So a `MessageGroupId` orders the starts, and a start that
fails holds the group's next one back until its retries run out; nothing stops a second run
beginning while the first is still going. File-ops' live check watched exactly that on 2026-09-10
(`docs/testing/owed.md`, *Two file operations in one space do not run at once*). The two queues a
Lambda event-source mapping drains, notifications and feedback, are the exception: a mapping runs
one invocation per FIFO group at a time, so their group ids do serialize their writers.

**What overlap does, plane by plane.** File-ops holds a per-space lock and the table-builder refresh
a per-table one, which is why neither appears below; the archive plane's arms are its own
[entry](archive-and-restore.md#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write).

- **Shared spaces: the name is unique without the queue.** `registry.reserve` creates the record
  with `If-None-Match: *`, so of two users submitting one name at once one is refused
  `name already taken` and the winner's record is untouched; the constant group id adds nothing to
  that. The registry's other writes, bar the final delete, the per-user cache and the membership
  index re-read and write under ETag CAS, which keeps each document whole. What CAS does not
  re-check is what the verb was authorized on — **and a CAS on one document orders nothing against
  a write to another, which is the second half of this arm.** **Repaired 2026-09-15 (Andrew), in
  the granting direction only:** `save_members`, `set_status` and `empty_space` now take an
  `expected_owner` and refuse with `OwnerChanged` — passed by the add, and only for a delta that
  actually ADDS somebody, since one that grants nothing needs no re-authorization and refusing it
  would turn an idempotent no-op into a failure. The delete carries it on the cascade's FIRST
  WRITE, the deleting status, rather than on a read: a read can only be re-checked by the write
  after it, and there a refusal has written nothing to a record it may not touch, and hands the
  space back rather than writing `failed` onto a record that is now somebody else's. **A transfer
  landing LATER, during the revocation loop, is not caught — and that is the decision, not the
  gap.** Three arrangements were tried and each was worse, which is the part worth keeping:
  refusing on the emptying rewrite arrives after every grant is gone, the new owner's included,
  and an owner's slot is one no ordinary verb can re-issue because the add normalises the owner
  out; emptying before revoking closes that but clears the owner and roster before anyone is
  revoked, so a Lambda killed mid-loop — a timeout is none of the four errors this fleet's
  machines retry — strands every unreached grant on a record naming nobody, unreachable even by a
  retry; and a repair that gave the revoked grants back wrote the new owner a MEMBER card, could
  re-grant over a delete the new owner had meanwhile started, and swallowed the one failure that
  mattered. Losing the space to a late delete is recoverable — the objects, the database and the
  name all survive an emptying, which is why emptying exists — and a grant nobody can see is not.
  **Revoking first is kept for a different reason than the refusal**: a FAULT in the main loop
  leaves the record untouched and the retry idempotent. It does not make a hard KILL safe, it
  only shrinks the stranded population to the latecomer pass, since the rewrite has blanked the
  roster by then and the replay reads it back empty.
  `set_owner` now also refuses a target who left the roster
  (`TransferTargetNoLongerMember`), which closes an owner who is not a member: being the owner is
  itself the access. **`remove_members` is deliberately NOT repaired** — a late remove revokes
  rather than grants, and `MembershipRefused` already decides that refusing one strands a member
  who slipped through; `expected_owner` is a general parameter, so it is one line if that reading
  changes. The roster fan-out now runs under the owner the COMMIT carries, at all four sites that
  passed the validator's, and writes nothing at all when the commit carries none — which also
  stops a late leave or remove re-creating every member's cache card for a space a delete has just
  emptied. Those cards are the browser's affordances, re-authorized at the validator, so that half
  was cosmetic. **The membership index was not:** the add wrote it AFTER its registry commit, so a
  delete's revocation landing in between let the add re-create the entry — `status` active, which
  is what an emptied record deliberately keeps — and the API's index source stamps a principal tag
  for any active entry. Reproduced against the verbs, and repaired the same day by writing every
  GRANT before the commit and only revocations after it, with the add rolling back both grants on
  any failure of the commit: a delete emptying after the commit finds the member in the record
  `empty_space` hands back, and one emptying before it makes the commit refuse. Latent while
  `MEMBERSHIP_SOURCE` is `claims`, which is every environment — the slot is the grant there, and
  the delete clears it. **Still live, and recorded rather than repaired:** CAS on an absent record
  writes create-only from the caller's snapshot, so an owner verb landing after a teardown's final
  delete recreates the record — `save_members` and `set_status` are the two that fall back that
  way, and the new owner check evaluates against that snapshot, so it does not close this; member
  actions are refused on anything not active, so it reaches only a never-active space, such as an
  owner's retried create racing their own delete. `create-space` writes its own index entry AFTER
  `finalize`, and that one cannot take the ordering above: the record reads `provisioning` until
  `finalize`, so an entry written earlier would name a space no session may reach — its own
  docstring argues that, and it still holds. So the create has the add's old shape, and it needs
  no absent record to bite: a creator deleting their own space in the window after `finalize`
  has their entry re-created over an emptied record, permanently, because an emptied roster names
  them nowhere any verb will sweep. A self-grant over their own retained objects, which is what
  caps it. `finalize` does **not** narrow this — it builds its record from a literal with no
  absent branch, so on a freed name it re-creates the record rather than refusing, which is the
  same create-only write as the two above and not a fence against it. The add's rollback is best-effort by design and skips anyone on the roster it reads, so
  on the destroying route a read landing before the record is deleted keeps both grants over a
  name that is then freed. The narrowing second index write has a residual of its own, in the
  denying direction: a delete dropping the entry between the commit and that write re-creates it
  non-granting, and nothing sweeps it, so a member can be denied a space the roster later allows. And the Cognito membership slots are no document at all:
  `assign_or_find_slot` reads the user's attributes and writes one slot with no condition, so two
  spaces adding one user at once can pick the same free slot, and the user keeps only one of the
  two grants while both rosters list them — a denial rather than a grant, in every interleaving,
  which is why it is the one left alone.
- **Table builder: a create still holds no lock, and now says so when it loses.** Two same-name
  creates in one database both pass `check-table-absent`, a point-in-time `GetTable` with
  `InspectSource` and `InferSchema` between it and the DDL, and the second
  `CREATE EXTERNAL TABLE IF NOT EXISTS` is a no-op over the first one's table. What changed
  (2026-09-15) is what that no-op is reported as. `execute-ddl` now reads the table back and refuses
  `table_exists` unless the catalog carries the LOCATION, the partition keys and the per-key
  projection properties **this** run declared — the three facts the request states, compared through
  the parser and the renderer the DDL itself used — so the loser is told the name is taken instead of
  that its table is ready to query. A replay still succeeds, because a retry meets its own table,
  which is the property `IF NOT EXISTS` is there for. The fix is a post-condition, not a lock:
  nothing is serialized, both runs still pay the whole inspection and inference, and nothing is
  overwritten. **The residual is the DATA COLUMNS, and only them** — two creates over the same
  folder whose partition declarations also match to the property agree on all three facts and are
  both told created, and the columns are then whichever run's inference landed. That is a
  difference of sampling rather than of request: both inferred from the LOCATION they agree on, and
  a single create already reads one sample file. **Every field the request itself states is
  compared**, which is why the projection is matched per key by EQUALITY inside that key's own
  `projection.` namespace and not by containment: `digits`, `interval` and `interval.unit` are
  optional, so a declaration without one is a strict subset of a declaration with it, and
  containment told a run declaring `month` its table was ready over a table generating `month=1`
  where its own request asked for `month=01`. Outside a declared key's namespace nothing is
  compared, so `projection.enabled` and any property AWS writes of its own accord cannot refuse an
  ordinary create.
  **A confirmation a run cannot make is reported as a failure, decided 2026-09-15 (Andrew).** That
  is the one thing here a user sees beyond the loser's refusal: a deterministic Glue fault on the
  read-back reports `ddl_execution_failed` over a table that exists, and a table still invisible
  after `ExecuteDdl`'s Retry reports the generic sentence, because the absence is raised as
  `TransientError` so the machine looks again rather than failing a create that landed. Both are
  near-unreachable — the role holds `glue:GetTable` and is this plane's LF admin, and a missing
  `CREATE_TABLE` grant fails the Athena statement long before the read-back — and the alternative
  was reporting an unconfirmed success as a success, which is the class this whole entry is about.
- **Table share: one table, told twice.** `check-target-absent` reads the catalog and then the
  prefix, the copy is an unconditional `CopyObject` into `{recipient}/shared_tables/{table}/`, which
  no run owns alone, and the create is `IF NOT EXISTS`. Two shares of one source to one recipient
  under one name, the second guarded before the first has created the table or landed an object,
  both clear the guard, copy the same keys and succeed, and each notifies; a double-submit that
  straddles the 60-second dedup bucket is enough. Anything written at
  those keys between the first copy and the second is overwritten. If the source is rewritten
  between the two runs' listings, the two can copy different object sets into the one location —
  each builds its manifest from whatever plan is at its plan key when it gets there, and two
  members' shares do not even share that key, since it digests the actor — and the table then
  reads both snapshots.
- **File send: an overlapping send can overwrite what the recipient did with the first.** The guard
  lists the names already in `shared_files/{sender}/`, and the copy is an unconditional `CopyObject`.
  A second send of an item to one recipient, submitted before the first run's copy of that name
  lands, clears the guard beside the first; it re-copies what the first delivered, and a file the
  recipient edited in between is overwritten with versioning off. The window lasts as long as the
  first run's copy, up to the three-hour ceiling, not only while two sends are "submitted close
  together". Separately, the plan and the manifest are keyed by request id and this plane has no
  `request_id_reused` refusal, so a hand-built request reusing an id past the five-minute dedup
  window shares both keys with the first, and one run can copy the other's plan — names its own
  guard never checked — over a recipient's files. The browser mints an id per submit and cannot.
- **Data quality: the request id is claimed.** Every per-run key — the temp tables, the manifest,
  the report, the query results and the Athena tokens — is derived from the request id, and one
  execution claims the id before any of them exists, so a second execution sending it past the dedup
  window is refused before it lists a file ([the claim](#a-data-quality-request-id-is-claimed-by-one-execution-before-anything-is-named-from-it-data-quality)). Two
  checks of one location with different ids are independent, and the runs index is written under
  ETag CAS.
- **Results conversion: the write is the guard.** The one object is written with `If-None-Match: *`
  unless the request asked to overwrite, so the loser of two overlapping saves to one name is
  refused `destination_occupied`. Two overwrites of one key land in the order they finish rather
  than the order they were submitted.

**Decided 2026-09-15 (Andrew): record now, and repair file send and table share in the follow-up
spec [decided the same day](archive-and-restore.md#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write)
for the archive restore's copy-back.** All three overwrite through the
one copy engine, `cpcommon.transfer`, and the repair chosen there — `If-None-Match: *` on
`CopyObject` and `CompleteMultipartUpload` — makes "never overwrites" true at every write on both
planes, which is the promise the Help page already makes for a send and for a share. It does not by
itself make the losing run report a conflict: the engine records a `412` as an ordinary per-item
failure, and both collectors turn any failed item into `copy_failed`, so the spec owes that mapping
too, and for table share an answer to two runs that each lose a key to the other and leave a
half-copied prefix with no table. The same spec adds a `request_id_reused` refusal to file send, as
archive and file-ops carry. Until it lands, the file-send and table-share arms above are live.
The table builder's misreported create is closed above, by a post-condition rather than a lock,
and its own residual is named there.

**The shared-space residuals were triaged separately on 2026-09-15 (Andrew), and the granting ones
repaired the same day.** The trigger was an audit claim that the add's membership-index write could
outlive a delete's revocation; it was reproduced against the verbs rather than taken on report, and
it is the only one of the six that grants under a source no environment runs yet. The rule that
came out of the triage, and that the arm above applies: **the direction decides the response.** A
residual that DENIES what the roster allows — the slot collision, a late remove — is recorded and
left, because refusing it strands somebody and the wrong choice costs a re-add. One that GRANTS
what the roster denies is repaired, and the repair is an ORDERING rather than a check wherever one
exists: a check across two documents has no atomicity to lean on, where writing the grant before
the commit makes a concurrent delete's own sweep the thing that catches it. What that ordering
costs is a member briefly holding a grant no roster shows, which is the shape the Cognito slot
already had and the reason a rollback sits beside it.

This audit corrected the sites it found claiming a group id serializes runs, and marked each one a
register, delivery doc or spec carried in place rather than rewriting it; the cancelled
file-converter spec, which never shipped, was left as it was. The Fences clause is what should catch
the next one, at authoring.

## A data-quality request id is claimed by one execution before anything is named from it (data quality)

**Every per-run name on this plane is derived from a request id the caller chooses.** The temp
tables, the report folder and everything under it — the manifest, the DDL and query output,
`report.json` — and the Athena `ClientRequestToken`s all come from `requestId`, which the API admits
as any string within its bound, and the queue forgets after five minutes. An id sent again past that
window while its first run was still going met the `IF NOT EXISTS` create as a no-op and inherited
the first run's LOCATION: a folder check reusing a root single-file check's id carried no `"$path"`
predicate over it. Only an accident refused those queries — the Athena tokens derive from the id
too, and Athena refuses a known token with a changed `QueryString` — and AWS documents no lifetime
for a token, so once one was forgotten the check reported over the whole space. It also overwrote
the first run's manifest and report, and either
run's cleanup dropped the other's table. In a shared space another member's ids are readable from
`index.json`.

**The id is claimed instead, once, by the execution.** `inspect-source` first writes
`data-quality/claims/{requestId}.json` to the admin bucket under `If-None-Match: *`, naming the
execution ARN that `StampExecution` puts on the state. A `412` reads the claim back: this
execution's own ARN is a Task retry and carries on, and anything else — a claim that does not parse
included — is refused `request_id_reused` before the verb lists a file. A `409` means a concurrent
request interrupted the create, and is retried. Nothing releases, takes over or expires a claim; a
test keeps every expiring admin-bucket lifecycle rule off the prefix. The refusal puts no
`manifestKey` on the state, so the failure path's cleanup drops nothing.

**A claim makes the names unique only if distinct ids derive distinct names, and they did not.** A
table's name is the id with its hyphens stripped, and Glue folds names to lower case, so `ab-cd` and
`abcd`, or an id and its upper-case twin, would hold two claims and share one table. The validator
and the claim both refuse anything but a lower-case hyphenated UUID as `invalid_request`, which is
exactly what the browser mints. The API still admits any string; the plane is the boundary.

**Rejected.** *Names derived from the execution:* `report.json` and the index row stay keyed on the
request id, which the browser computes, so closing that arm is a contract change. *A read-back of
the temp table's LOCATION*, table-builder's post-condition: it closes the predicate bypass alone,
adds a Glue and Lake Formation read this plane never made, and leaves the report, manifest, token
and cleanup arms open. *A claim beside the report:* it would sit inside the space, only as safe as
every route that can write or delete there, and be one claim per space rather than per id.
*Claiming in `validate-authorize`:* its payload is the raw Pipe array, one of the trace-adoption
shapes, and reaching the ARN there means reshaping it.

**Decided 2026-09-16 (Andrew): the refusal is silent.** The browser mints a fresh id per submit, so a
reuse comes from a request built by hand, which has nothing it should be told, and the run it
collided with is the one that reports. The question put to Andrew also gave a redelivery of one
click as the realistic trigger, one that would tell a person a running check had failed. That rested
on redelivery starting a second execution, and [reusing an execution name was measured](../../infra/info/control-plane-shape.md#a-redelivered-message-is-not-a-re-run)
to return the first run instead — only that a redelivery reuses its name is inferred — so the
decision stands on the reason above. The code and the predicate that keeps it quiet now live in the
shared layer, [where file operations and archive read them too](#a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is-the-one-that-reports-data-quality-file-operations-archive). That a notice under a borrowed id
could drop someone else's is closed for every plane at the queue, by [per-recipient deduplication](#notifications-deduplicate-per-recipient-so-a-borrowed-request-id-cannot-drop-someone-elses-notice-control-plane-wide).

**What stays open.** Runs from before the claim hold none, so reusing one of their ids claims it
afresh and overwrites that run's report and index row; there are no production users, so there is no
backfill. A reusing execution whose claim fails loudly — its retries run out, or reading the holder
back meets an unexpected error — is notified to its own sender, generically. And Deploy Lambdas and Deploy
Infrastructure race on the merge that introduced this: a verb pointed before the machine stamps the
ARN refuses every check `invalid_request` until the apply lands.

## Notifications deduplicate per recipient, so a borrowed request id cannot drop someone else's notice (control-plane-wide)

**A notice's dedup key is built from a value the caller chose.** Most producers pass
`{requestId}:{outcome}` — `cpcommon.notify.dedup_id` — and a request id is whatever the sender of the
request put in it. The requests queue deduplicated across the whole queue, so any notice sent under
another person's key within five minutes was dropped, whoever it was for. Repairing one plane turned
up two instances before the class was named: a data-quality run reusing another run's id and
refused would have been notified under the holder's `failure` key, and table-builder's failure
notices go out under the same shape of key, so a shared-space member who reads an in-flight check's
id from the reports folder listing could send a table-builder request under it and suppress the
check's failure notice — and the dashboard lists completed checks only, so nothing else says it
failed.

**The queue deduplicates within a message group instead, and the group is the recipient.**
`deduplication_scope = "messageGroup"` on the requests queue; `cpcommon.notify.emit_notification`
already sets `MessageGroupId` to the recipient's username, which is what makes the writer
single-threaded per user. A notice can now collapse only with another notice to the same person,
which is every duplicate a producer means to collapse — a verb and the notify state reporting one
failure — and a borrowed id reaches only the borrower's own notices. The shared-space producers that
put a recipient in their keys to survive the old scope are unaffected.
Throughput stays per queue: `perMessageGroupId` is the high-throughput mode, which nothing here
needs. The attribute updates in place — the provider does not replace a queue for it.

**Rejected: fixing each producer.** Keying data quality's failure notices on the execution ARN
closes that plane alone and leaves table-builder, file-ops and archive keyed as before; a key per
producer is the per-site answer the class had already outrun twice.

**What it does not change.** The same person can still lose a notice to another of their own under
the same key — two of their requests sent with one id — because that is what deduplication is for.

## A reused request id is told to nobody, because the run holding the id is the one that reports (data quality, file operations, archive)

**All three planes that refuse `request_id_reused` refuse it silently.** Each decides that an id is
held its own way — data quality by a claim naming another execution, file operations by a plan naming
another execution ARN, archive by an archive prefix that already holds objects — and in each the id
belongs to a run that reports under it: data quality's report notice, file operations'
`{requestId}:outcomes` row, archive's `archived` and restore rows. A notice from the refused run could
only contradict that run. On file operations it said *"that looks like a repeat of a request already in
flight. Nothing was changed"* and carried `{requestId}` with no `operation`, so it could settle the
browser's in-flight card as *Refused* on an operation that finished. On archive it said nothing was
archived, beside *"Archived N files"*. Neither dropped the first run's notice — its success rows carry
explicit dedup ids and the failure text differed — so this was wording, not a lost message.

**Decided 2026-09-16 (Andrew): silent on file operations and archive, as on data quality.** Rewording
the notice to say a duplicate was ignored was the alternative, and it would still land a row carrying
the card's id. Who actually sends a reuse is argued in [the data-quality entry](#a-data-quality-request-id-is-claimed-by-one-execution-before-anything-is-named-from-it-data-quality): the browser
mints an id per submit, and a redelivered message was measured to return the running execution rather
than start another. So the likely sender is a hand-built request, which is now told nothing and finds
its refusal on the execution.

**The mechanism is one vocabulary and one predicate, both in the shared layer.**
`cpcommon.messages.SILENT_REASONS` holds the code and registers it at import, and
`cpcommon.notify.is_silent` is what each plane's `emit_failure` reads before it sends.

- **The shared layer registers the code, not each plane.** The suite imports every domain into one
  process, so a plane that forgot to register a code another plane registers passes locally and raises
  `ValueError` in its deployed function, where the error is no longer a `TerminalError` and the user is
  told twice that something went wrong. Data quality's first version registered its own copy. A test
  in a fresh interpreter holding only `cpcommon` holds the new home.
- **The check sits in `emit_failure`, not in `notifies_on_failure`.** The validators call their plane's
  `emit_failure` directly, and a check in the decorator would miss them.
- **A `Resolver` refuses a domain that words a silent reason.** File operations and archive each
  carried a body for it, now deleted, and a sentence nobody is told reads to the next person in the
  table as what the user sees.

**The other half of the silence is `notify-failure`, and it differs by plane.** File operations' and
archive's drop every `TerminalError` as already handled, so a silenced reason stays silent there
without reading the predicate; data quality's reads `is_silent` itself. A test on each of the first two
pins that half, because narrowing their name check would send the fallback *"something went wrong"*
while every verb test stayed green.

**A plane that adds the refusal gets the registration for free and the silence only by asking.** File
send is due one; it is silent only once its own `emit_failure` reads `is_silent`.

**Rejected.** *A copy of `SILENT_REASONS` and `is_silent` in each domain*, data quality's first shape:
three copies of one policy, each carrying the registration trap. *Reading the predicate in file
operations' and archive's `notify-failure`*: dead on the only path it would guard, since that state
already drops the error.
