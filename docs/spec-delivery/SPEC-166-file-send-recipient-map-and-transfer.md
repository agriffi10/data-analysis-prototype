# Completed Spec — SPEC-166: Send Files — Recipient Guard, Distributed-Map Transfer & Terminal States

## What was completed?

A send that reaches the plane now delivers files. The plan SPEC-165 wrote is guarded per
recipient, expanded into a `(recipient × object)` manifest, copied by a top-level Distributed Map,
and attributed back to the people it was for. The user still hears nothing — that is SPEC-167.

- **`file-send-check-target-absent`** — the per-recipient conflict guard, one delimited listing of
  the recipient's inbox each. Its per-item `Catch` is left for unpredicted faults; the two
  refusals it *expects* come back as records.
- **`fscommon.inbox`** — `existing_item_names`, the listing that answers the guard's question.
- **`file-send-build-transfer-manifest`** — one JSONL line per `(accepted recipient × planned
  object)`, every destination from `fscommon.paths.destination_key`.
- **`file-send-copy-objects`** — `cpcommon.transfer.copy` with this plane's reason code, and
  nothing else.
- **`file-send-collect-transfer-results`** — `SUCCEEDED_n` **and** `FAILED_n`/`PENDING_n`, the item
  count reconciled against the manifest, one uniform outcome per recipient, plus the item names
  the summary reports.
- **ASL** — `InspectSource → GuardRecipients → BuildTransferManifest → HasTransferItems →
  TransferObjects → CollectTransferResults → ShapeSummary → Succeeded`, with a top-level
  `TimeoutSeconds` and an EventBridge `TIMED_OUT` rule beside it.
- **IAM** — `*/shared_files/*` writes on the execution role, the Map's `states:`/S3 grants on the
  **state-machine** role, `states:DescribeExecution` for the timeout door, and the deploy role's
  `events:` grant for the rule.
- **Three PRs**: the verbs and their grants (#425), the wiring, the caps and the ceiling (#426),
  then completion (#427).

## An expected refusal is a return value, not an exception

Table-share's guard raises `TerminalError` for every refusal and its Map item's `Catch` records
it. This plane's guard returns `{status, recipient, reason, detail}` for the two refusals it
expects — an unresolved recipient and a name conflict — and keeps the `Catch` for faults nobody
predicted.

The reason is FR-001 AC5: a conflict has to name the colliding item so SPEC-167 can tell the
sender *which* file was already there, and a raised `TerminalError` **cannot carry it**. Its
`tokens` are deliberately kept out of the exception message (they would corrupt
`failure_reason`'s colon split), and its `detail` is operator text that may quote raw service
output and must never reach a user (SPEC-106). Parsing a filename back out of a Step Functions
`Cause` would be fragile *and* a rule break. So the collector reads two record shapes — a
`reason` string, or a raw `{Error, Cause}` it decodes with `cpcommon.errors.failure_reason` — and
neither the guard nor the collector notifies anybody, because every per-recipient outcome is told
to the sender **once**, from the terminal summary, by SPEC-167's producer.

## The inbox is read with a delimiter, and the obvious probe is wrong twice over

The guard asks one question: *is any name this send would create already taken?* It answers it
with one delimited listing of `{targetRoot}shared_files/{sender}/`.

Probing `{inbox}{item}` per item costs two round trips each — 200 items against a 50-recipient Map
is 20,000 serial calls — and, more importantly, **a `MaxKeys=1` probe cannot answer it**. S3
returns keys in lexicographic order and `/` (0x2F) is not the lowest byte a key may carry, so
`notes.txt-old` sorts *before* `notes.txt/part-0`: the one key returned says "clear" over an
occupied destination. A delimiter listing sidesteps both, is bounded by what that sender has
previously sent to that recipient rather than by the size of the send, and gives the colliding
name exactly as the recipient sees it.

A name is a name whatever it holds: a previous send of the *file* `notes.txt` conflicts with a new
send of the *folder* `notes.txt/`, because `destination_key` gives both the same base and merging
is not a behaviour this plane has.

## The caps are three, and each is computed against a different thing

| cap | value | what sizes it |
|---|---|---|
| `SEND_MAX_OBJECT_BYTES` | 10 GiB | a batch is one round of the worker pool and **one object is one worker**, so the budget is `COPY_TIMEOUT_SECONDS` — the batch verb's own Lambda timeout, not the machine's ceiling |
| `SEND_MAX_TRANSFER_ITEMS` | 50,000 | the manifest's length, against the memory the two verbs either side of the Map hold it in — read back **from `locals.tf`** |
| `SEND_MAX_TRANSFER_BYTES` | 3 TiB | the whole run's makespan at **500 MB/s**, against the machine's `TimeoutSeconds` |

The per-object cap is the one SPEC-165 recorded as owed and measured the hole for: without it the
worst legal case was a single 1 TiB object on one worker — 43,980 s, four times the ceiling — while
every distributed model read as satisfied. It is table-share's value exactly, and deliberately so:
same engine, same batch size, same timeout, so a different number would mean one of them was
wrong.

`SEND_MAX_TRANSFER_ITEMS` **diverges** from table-share's 20,000, and that is argued rather than
inherited. Table-share's transfer cap equals its own object cap, so at full size it permits one
recipient — fine when a share is one table. Sending a 2,000-file folder to a 30-person team is the
ordinary case here and 20,000 would refuse it. The computed memory ceiling is ~150,000 items;
50,000 takes a third of it, and the verbs' 300-second timeouts are not the binding term (computed
too, at two orders of magnitude of headroom).

Both product caps are measured on the **requested** recipient count, before the guard runs.
Counting only cleared recipients would let the expensive half of the work happen first — the guard
is one listing per recipient — and would make a refusal depend on what someone else's inbox
happens to hold.

## The ceiling, and why it ships with a rule

`TimeoutSeconds` is 10,800 as a **top-level** ASL field. Without one a Standard workflow's ceiling
is Step Functions' own default of a year, and this is the first version of this machine that can
wedge, because it is the first with a Map, a manifest and a copy in it.

It cannot notify on its own. AWS catchers cover Task, Parallel and Map states but **not top-level
execution failures**: the timeout terminates the run outright, so no state runs and no `Catch`
fires. So it ships with an EventBridge rule on `TIMED_OUT` (**never** `FAILED`, or every caught
failure would double-notify), a second door in `fs_notify_failure`, that verb's 15s → 60s raise for
the JWKS fetch that door does, and the deploy role's `events:` grant for the rule.

`test_the_whole_run_fits_the_machines_ceiling` adds up **every** term rather than asserting the
total: copying 6,597 s + per-child overhead 939 s + the guard Map 600 s + the four serial verbs
735 s = **8,871 s**. Only one input has no measurement behind it — the per-*round* child overhead —
and the test says so, along with its break-even (~9 s per round against a ~1,900 s margin).

## The timeout door needed a fallback table-share does not

EventBridge caps an event at 256 KB and Step Functions drops the execution input rather than exceed
it. On table-share the input is a table name and a recipient list; here `SEND_MAX_ITEM_BYTES`
deliberately allows a Pipe record approaching 200 KB — so **the sends most likely to run for three
hours are exactly the ones the event alone cannot attribute**. The door reads the input back with
`states:DescribeExecution`, granted on the **Lambda execution role** (EventBridge invokes the
notifier outside any execution) and asserted as the only `states:` action there. Inheriting
table-share's shape without re-checking it against this plane's much larger input would have left
FR-005 AC1 half-delivered.

## Two fail-open holes and a 256 KB seed, found in review

All three were caught by the fresh-context reviews and none by the suites as written:

- **The guard cleared every recipient when the selection arrived empty.** No names to check ⇒ no
  collisions ⇒ `ok`, over an inbox that already held the send. Unreachable through
  validate-authorize, reachable through a Map `ItemSelector` that stopped threading the source —
  and the asymmetry was three lines away, where a missing *actor* already failed closed. Now
  `no_items`.
- **The collector reported universal success when the `transfer` block went missing** — no S3 call
  at all. Closed with an invariant already on the event: the manifest builder cannot report zero
  items while a recipient cleared the guard, because the plan reader refuses an empty object list.
- **`RequestFailureSeed` carried `$.raw` *and* `$.source`** — the ~200 KB Pipe record plus the same
  selection again, ~300 KB for a quote-heavy legal request. `States.DataLimitExceeded` on a Pass
  with no `Catch`, killing the run before `NotifyFailure`, at the end of a three-hour copy. The
  selection is dropped from the seed and from `RecordFailure`; the guard that should have caught it
  modelled only the *pre-identity* seed and now models both.

## What the tests could not see, and now can

Four ASL↔verb couplings had no cross-check, and the reviewer's mutations survived the entire
suite — including renaming the guard Map's `ResultPath`, which makes **every send report success
having copied nothing**. Each now fails on mutation (verified by patching the template): the
guard's `ResultPath` is driven through the real manifest verb, the `$.transfer.*` reads are held
against what that verb emits, the `ItemSelector` is driven through the real guard verb, and the
Map's concurrency must come from the named local.

The catch walk's availability model was rebuilt for the same reason. It derived what was on the
state from the *immediately preceding `Pass`* — true while the machine was two Tasks, and silently
an empty set the moment a Map or a Choice sat between them, which is exactly what this spec adds.
It now walks the success path forward through the verbs' **real, chained** outputs (validate →
inspect → manifest → collector, with the fake S3 serving back what was written to it), taking the
**intersection** at join points so `mapRun` — which only one Choice branch adds — is correctly not
treated as available.

## Deliberate deviations

- **The manifest key carries no execution name**, where table-share's does. Table-share has no
  request id, so its keys are a digest two overlapping executions collide on. Here the id is the
  browser's per-submit `MessageDeduplicationId`, and a second execution carrying it could only come
  from a redelivery the Pipe's deterministic execution name refuses with `ExecutionAlreadyExists`.
  What the key must buy is that a *Retry* rewrites one object rather than leaving two.
- **A third cap, `SEND_MAX_TRANSFER_ITEMS`, beyond the two the spec's own notes anticipated.** The
  manifest is `objects × recipients`; without it the legal worst case is a million lines, which is
  neither verb's memory. Recorded here rather than left as "the spec said two".
- **The guard's conflict check is TOCTOU**, and FR-001's "no send ever overwrites anything" is
  stated absolutely. Two sends of the same item name from the same sender to the same recipient,
  submitted close together, can both clear the guard. Inherent to check-then-copy with no lock —
  table-share is the same shape — and not closed here.
- **A selected item that expands to zero objects still consumes a name in the guard.** The guard
  reads names from the selection and the write set comes from the plan, so an empty folder can
  refuse a recipient without contributing a destination. Fail-safe, and spec-compliant ("any
  selected item name"), but the two documents are decoupled and it is worth knowing.
- **No component-inventory rows**, for the reason SPEC-165 recorded: the inventory is browser-only
  and no plane's Python layer appears in it.
- **Nothing user-facing changed**, so no Help & guides edit. The feature is still silent; SPEC-167
  ships the entry point, the dialog, the notifications and the guide together.

## What changed from earlier specs?

- **`cpcommon.clients`** gained `sfn()`. No behaviour change for any existing caller.
- **`fscommon.paths`** gained `inbox_prefix`, and `destination_key` now composes it — one prefix,
  used by the builder and by the guard's listing.
- **`fscommon.copy_plan`** gained the manifest key, the results prefix and `load`, whose
  completeness checks (an object count reconciled against the list, a named sender and source
  bucket, a shape check per entry) are what make its own docstring true.
- **`Planned` is gone** and `InspectFailureSeed` is now `RequestFailureSeed`, because five states
  reach it.
- **`fs_notify_failure`** has a second door, and `notify-failure` runs at 60s.

## Live checks (owed)

`docs/testing/file-send-e2e.md`, *SPEC-166* — checks 7–9. They are the only evidence that the
cross-bucket write actually lands: **nothing that runs offline proves the `*/shared_files/*`
scoping works**, and a policy simulation without `--resource-policy` returns `allowed` for a
`PutObject` the real call denies, which is worse than no simulation.
