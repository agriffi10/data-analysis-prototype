# Completed Spec — SPEC-161: Table Share at Scale — Raised Caps, Wide Definitions & Long Runs

## What was completed?

SPEC-160 built the engine; this spec moved the ceilings that were written for the Lambda it
replaced. A table of several hundred part files well over 20 GiB, with a hundred commented columns,
now shares — where before it was refused twice over, both times for reasons that had stopped being
true. Nothing about the request contract, the push semantics or the notifications changed.

- **The caps.** `SHARE_MAX_OBJECTS` 1,000 → **20,000**, `SHARE_MAX_TOTAL_BYTES` 20 GiB → **1 TiB**,
  a new **`SHARE_MAX_TRANSFER_ITEMS` (20,000)** on `recipients × objects`, and a new
  **`SHARE_MAX_OBJECT_BYTES` (10 GiB)** on a single object — which also moved SPEC-160's
  `MAX_ITEMS_PER_BATCH` 50 → **8** — plus **`SHARE_MAX_TRANSFER_BYTES` (3 TiB)** on
  `recipients × bytes`, the byte-axis twin of the item cap. `SHARE_MAX_RECIPIENTS` stays 50,
  pinned by a test rather than by absence. Each docstring names the limit that sized it.
- **The definition travels by pointer.** `inspect-source` writes
  `{admin_bucket}/table-share/{hash}/definition.json` and emits `definitionKey`; `create-table`
  fetches it. `tscommon.copy_plan` gained `definition_key` / `write_definition` / `load_definition`,
  keeping every admin-bucket key this plane writes in one module. **No IAM change** —
  `CopyPlanReadWrite` already covered `PutObject`/`GetObject` on `table-share/*`.
- **`SHARE_MAX_DEFINITION_BYTES` 32 KiB → 64 KiB**, re-expressed as an object-size sanity check.
  What sizes it now is Athena's query-string quota, **262,144 bytes and not adjustable** (verified
  against the live service-quotas page), because the definition renders into one
  `CREATE EXTERNAL TABLE`.
- **A top-level `TimeoutSeconds` of 10,800**, from a named local, so a wedged run terminates instead
  of running to Step Functions' one-year default — **plus an EventBridge `TIMED_OUT` rule**, because
  the timeout alone cannot tell anyone (see below).
- **The retired refusal wording is gone** from `lambdas/`, with a fleet-wide sweep holding it out.

## The `TimeoutSeconds` arithmetic

**The bound is `SHARE_MAX_TRANSFER_BYTES`, not `SHARE_MAX_TOTAL_BYTES`, and getting that wrong is
finding 3 below.** The manifest carries one item per (recipient, object) pair and every item is a
full copy, so the Map moves the source once *per recipient*.

**And the rate is a makespan, not an aggregate bandwidth** — finding 4. `copy_batch` gives one
whole object to one worker and `copy_one` part-copies serially, so a batch dominated by one large
object runs at *one* stream while seven idle.

| term | value | where from |
|---|---|---|
| pessimistic rate | **500 MB/s** | `MAP_MAX_CONCURRENCY` (20) × `CONSERVATIVE_STREAM_BYTES_PER_SECOND` (25 MB/s) — **not** × `COPY_CONCURRENCY` |
| copy | **6,597 s** | `SHARE_MAX_TRANSFER_BYTES` **3 TiB** ÷ 500 MB/s |
| the finish Map's Athena creates | **3,000 s** | ⌈50 / `MaxConcurrency` 5⌉ × `create-table` 300 s |
| the serial verbs | **720 s** | inspect 120 + manifest 300 + collect 300 |
| **total worst run** | **10,317 s** | vs **`TimeoutSeconds` 10,800 s (3 h)** |
| *what two earlier models said* | *4,398 s* | *16 TiB ÷ an aggregate 4.0 GB/s — the real figure is 35,184 s* |
| *and before that* | *50 TiB* | *50 recipients × the 1 TiB source cap — 3.8 h, over the ceiling* |

It is deliberately not longer. The timeout is how quickly a wedged share becomes a notification, so
the margin is bought against the sender's silence rather than being free — the cap moves before the
timeout does. `test_the_timeout_is_fed_from_a_named_value_and_clears_the_caps` **computes** this
from the constants; the hard-coded floor that stood there first is what let the mismatch ship.

**Retention clears it by 240×.** `admin_results_retention_days` is 30 (720 h) against a 3 h run
ceiling, so `expire-table-share-copy-plans` cannot expire a live run's manifest underneath it. A
test computes that ratio from both files.

## FR-003 AC2: a top-level timeout cannot notify anyone, and review caught it

The first cut of this spec shipped `TimeoutSeconds` alone and claimed in four places that a timed-out
run would reach `NotifyFailure`. **It would not.** AWS is explicit: *"Step Functions catchers are
available for Task, Parallel and Map states, but not for top-level state machine execution
failures"* — the expiry terminates the run outright, so no state runs and no `Catch` fires. The
state sits in the machine looking exactly like it would work.

That is worse than it first appears. A `TimeoutSeconds` shipped alone would have **bounded the run
and made the sender's silence permanent instead of merely long**, with SPEC-152's guarantee reading
as satisfied by a state that could never be reached. The test written for AC2 was vacuous — it
asserted the pre-existing `RecordFailure → NotifyFailure` wiring and passed with `TimeoutSeconds`
deleted.

**The fix is the remedy AWS names**: an EventBridge rule on `Step Functions Execution Status Change`
matching **`TIMED_OUT` only**, invoking the same `notify-failure` verb through a second door.

- **`TIMED_OUT` only is load-bearing.** Every other whole-request failure already reaches the verb
  through a `Catch` and ends at `Fail`, whose status is `FAILED`. Matching both would send a second
  notification for every caught failure. The doors are disjoint by construction, not by suppression.
- **The sender comes from the token, not the body.** The execution input is the Pipe's forwarded SQS
  batch, so the actor is the verified `cognito:username` inside the body's ID token. Expiry is
  deliberately not enforced — by construction the token is expired, since the timeout fires hours
  after it was minted — through the DLQ drain's separately-named `verified_username_ignoring_expiry`.
  Safe for the same reason: this path grants nothing, it addresses a message.
- **Unattributable is a logged no-op.** EventBridge caps an event at 256 KB and Step Functions omits
  an input too large for it, so `inputDetails.included: false` is a real shape. No guessed inbox.
- **Its own wording, `share_timed_out`.** A timeout is the one whole-request failure that can leave a
  recipient holding *part* of a dataset — the copy may have run and the create may not — so the
  generic "try again" would be wrong advice.

Deploy-role IAM gained one `events:*` statement scoped to this rule's ARN; the invoke is a
resource-based `aws_lambda_permission`, so no invoke role, matching the DLQ drain's sweep.

## What FR-004 required was adding nothing

All three artifacts — manifest, `definition.json`, the `ResultWriter` export — sit under
`table-share/` **by construction**, because `tscommon.copy_plan` owns every key this plane writes.
So the existing rule covers them: no new rule, no new rule id, and the
`admin_lifecycle_rules_are_prefix_scoped` check untouched. Three tests now assert the absence — the
retention margin, that exactly one `table-share/` rule exists, and that the execution role's
`s3:DeleteObject` deny still covers the admin bucket (read from the **raw** template, because the
stubbed policy collapses every ARN placeholder to one literal and could not tell the admin bucket
from a space bucket).

## Deliberate deviations

- **The two manifest verbs were re-sized**, which the spec does not name: `build-transfer-manifest`
  and `collect-transfer-results` go 60 s/512 MB → **300 s/2048 MB**. They *are* the binding
  constraint on `SHARE_MAX_TRANSFER_ITEMS` — at S3's worst-case 1024-byte keys, 20,000 items is a
  ~46 MB manifest and an export carrying every batch's input back again. Memory is also the CPU
  dial, so it buys the timeout as much as the headroom. A test computes the worst-case volume from
  the cap and the same worst-case item the batch sizing uses, so raising the cap without re-sizing
  the verbs fails.
- **The item cap counts *requested* recipients, not guard-accepted ones.** Refusing on the upper
  bound is predictable from what the sender asked for; refusing on the accepted count would make an
  identical request succeed or fail depending on who already happened to hold a table of that name.
  It also fails before the guard, so an over-cap share costs no Glue reads and no listings.
- **A new reason code, `definition_unreadable`**, rather than reusing `create_failed`. FR-002 AC5
  wants a clear reason, and the failure is genuinely a different thing from a DDL that ran and
  failed.
- **A new cap the spec does not list, and a SPEC-160 constant changed: `SHARE_MAX_OBJECT_BYTES`
  (10 GiB) with `MAX_ITEMS_PER_BATCH` 50 → 10.** Raising `SHARE_MAX_TOTAL_BYTES` to 1 TiB introduced
  a regression nothing else would have caught, and it took two goes to bound correctly. **The unit
  that must copy inside `copy-objects`' 900 s is a BATCH, not an object** — `ItemBatcher` batches by
  count, never by bytes. While the total cap was 20 GiB that bound was implicit, because a batch
  could not exceed the whole table; raising the total removed it with nothing replacing it. A
  per-object cap alone does not restore it: at 50 items × 20 GiB the worst batch is **1000 GiB**,
  over 900 s even at an optimistic 100 MB/s per stream. The pair now holds `batch × per-object` at
  **100 GiB** (~537 s at a conservative 25 MB/s per stream over 8 workers), computed by
  `test_a_worst_case_batch_copies_inside_the_verb_timeout`. **(10 GiB × 10) was chosen over
  (2 GiB × 50)** because it stays above S3's 5 GiB single-copy limit, keeping the multipart
  part-copy path reachable rather than dead code; the price is ~5× the child executions on a
  many-small-files share, which is state transitions and Lambda invocations, both cheap.
- **`architecture.md` and `ARCS.md` were edited, which Phase 5 said not to do.** That instruction
  comes from FR-005's last criterion, and reading it in context it is scoped to the *refusal
  wording* — those docs were already corrected for the Batch Ops fence on 2026-08-10, so re-editing
  them **for that** would mean one had been missed. It does not cover FR-001, which supersedes a
  different fact. Left alone, `architecture.md` would still read *"The caps still stand"* and
  `ARCS.md` would still describe 161 in the future tense. Both got a short in-place superseded
  marker, per the standing completion ritual; neither mentions Batch Ops.

## Two things worth carrying

- **The payload-limit model now proves the pointer rather than assuming it.**
  `test_the_whole_map_state_stays_under_the_payload_limit` adds a worst-allowed definition back to
  the modelled state and measures the result: the guard peak goes from ~34% of the 256 KB limit to
  ~55%. Not a breach at 64 KiB — and that is the finding in both directions. Inline, the cap had to
  choose between the payload and the user, and the old 32 KiB value kept the state safe only by
  refusing a 100-column commented table.
- **The retired-phrase sweep caught one of this spec's own test docstrings**, which quoted the
  phrase while explaining its removal. Reworded rather than exempted. No existing test asserted the
  old wording — the suites assert `exc.reason` and the user sentence, neither of which ever carried
  it — so a grep is the only thing standing between a stale operator-facing detail and the next
  operator to read a failed run.
- **The definition cap is measured against Athena's quota, and it took two goes.** The first cut
  claimed 128 KiB "leaves roughly a factor of two". It does not: `ddl.literal` backslash-escapes, so
  a `'` costs one byte in the JSON the cap measures and **two** in the DDL. The first test built
  apostrophe-heavy *comments* and measured 87% — but **where the quotes sit decides the ratio**. A
  column carries ~40 bytes of JSON overhead per comment (1.7×); a **table property or SerDe
  parameter** carries ~9 and renders at nearly the full 2×. The real worst case at 128 KiB is
  **262,082 of 262,144 bytes — 99.98%, sixty-two bytes of margin**. The cap is now **64 KiB**, where
  the same worst case lands at 50%, and the test builds the property-shaped fixture with
  max-length identifiers.

## Finding 3: the timeout was sized against one copy of a table the Map copies N times

Three review rounds, three bounds applied at the wrong unit, each one axis further out than the
last. This was the third and the largest: `SHARE_MAX_TOTAL_BYTES` caps the **source**, but the Map
transfers `source × recipients`, and nothing bounded that product. The worst share every cap
accepted — 50 recipients × a 1 TiB source, with 400 objects keeping `recipients × objects` exactly
at 20,000 — is **50 TiB**, which needs 3.8 h at the conservative rate, 4.8 h at 20 MB/s and 19.1 h
at the pessimistic 5 MB/s. All three exceed the 3 h ceiling. Break-even is **8 recipients** at
5 MB/s and **40** at 25 MB/s, so it was not only reachable at the corner.

The sender would have waited three hours, had the run killed mid-copy, and been told (correctly, by
the door added in round 2) that recipients may hold partial data. A better failure than silence, but
FR-003 AC3 — *"the timeout is larger than the worst-case run implied by the FR-001 caps"* — was
false as shipped.

**What made it invisible is worth more than the fix.** The spec's own reasoning for
`SHARE_MAX_TRANSFER_ITEMS` says it plainly: *"20,000 objects is fine and 50 recipients is fine, and
together they are a million manifest lines."* That argument was applied to the item axis and never
to the byte axis, and the timeout's arithmetic was then written against the un-multiplied number, so
every doc restating it agreed with every other. Round 2's batch fix did not help either — batch
50 → 10 changes per-batch duration, not total wall clock, because `MAP_MAX_CONCURRENCY` is the
throughput limiter.

`SHARE_MAX_TRANSFER_BYTES` now closes it, enforced in the same pass as the item cap, and the
FR-003 test computes the timeout against it instead of asserting a floor.

## Finding 4: the rate was an aggregate bandwidth the copy path cannot deliver

A fourth round, and the same class one level down. Every time bound divided bytes by
`MAP_MAX_CONCURRENCY × COPY_CONCURRENCY × rate`, as though bytes flowed through 160 pipes.
`copy_batch` submits **one whole object per worker** and `copy_one`'s multipart loop is serial, so
an object holds a worker for `size / rate` however idle the others are. The schedulable unit is an
object on a worker; the cost is a **makespan**, not a bandwidth. And `ItemBatcher` has only
`MaxItemsPerBatch` — nothing balances a batch by size.

Two bounds were wrong as a result, and both tests encoded the same wrong model, so both were green:

- **Batch.** 10 items × 10 GiB on 8 workers is ⌈10/8⌉ = **two** rounds of 429 s = **859 s** against a
  900 s Lambda timeout — 41 seconds of margin, where the test claimed 537 s against a 600 s budget.
  Fixed by setting `MAX_ITEMS_PER_BATCH` = `COPY_CONCURRENCY` = **8**, so a batch is exactly one
  round and costs one object's time. `test_a_batch_is_exactly_one_round_of_the_worker_pool` makes
  that structural rather than arithmetic — above the pool size the cost doubles at the first item
  over, a step change no bytes-based bound can express.
- **Run.** A mixed-size Parquet table (one large part per ten — ordinary, not adversarial) degrades
  effective concurrency from 160 streams to 20. 16 TiB at the real 500 MB/s is **35,184 s**, not
  4,398. `SHARE_MAX_TRANSFER_BYTES` drops to **3 TiB**, and the FR-003 test now subtracts the finish
  Map and the serial verbs from the ceiling instead of pretending the copy owns all of it.

**What this round should be remembered for** is that four bugs in a row were one bug: a bound
compared against a quantity the system does not actually produce. State payload vs. Athena's query
string; object vs. batch; source vs. source × recipients; bandwidth vs. makespan. The countermeasure
that worked was never a bigger margin — it was making each test *compute* its bound from the
constants and derive the model from the code, so a wrong model fails loudly instead of reading as a
comfortable number.

## A multi-recipient ceiling worth stating

`SHARE_MAX_TRANSFER_ITEMS` equals `SHARE_MAX_OBJECTS`, so the object cap is only reachable by a
single-recipient share. 500 objects can go to 40 recipients; **500 objects to all 50 is refused** at
25,000 items. That is a deliberate consequence of bounding the product, and the refusal names both
numbers — but it is a shape a user can meet without doing anything unreasonable, so it is recorded
here rather than left to be discovered.

## Owed

- **The live check** — the runnable script is in `docs/testing/e2e.md` §4.10 Table share:
  the >20 GiB several-hundred-object share, the deliberate over-cap refusal naming the count and the
  cap, and a `GetTable` read-back confirming a 100-column commented definition survived the pointer.
  The recipient's own count ran on 2026-09-21 and matched the source's, 150 rows
  (`docs/testing/sessions.md`, 2026-09-21 night); the scale pass above is still owed.
- **Nothing user-facing to document.** `helpContent.ts` names no cap numbers and no size limits, so
  the SPEC-074 sweep is a genuine no-op here, not a skip.
