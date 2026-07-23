# Completed Spec — SPEC-131: Narrate the Log Sweep

## What was completed?

`lambdas/log-sweep/log_sweep.py` now writes its story to the store it feeds, not only to
CloudWatch. **Nothing about what the sweep does changed** — routing, partitioning, the CAS loop,
the cap, delete-after-write ordering, the schedule and the key layout are untouched.

- **Intake** — `received` (messages + day-groups), a `receive` child span (the poll loop is billed
  per round and fails differently from the writes), a truncation warning. An **empty sweep
  narrates nothing**: it fires 144×/day and is usually empty.
- **Destinations** — an `append-day` child span each, with entry and success events naming the key
  and the resulting object size, and a failure event carrying a **stable reason token**
  (`precondition-exhausted` / `write-failed`) instead of a stringified exception.
- **Degraded paths** — CAS retry (once per attempt: the retry *count* is the contention signal),
  large day object, undated events, failed delete, unroutable bodies.
- **Outcome** — one event with `written` **and** `failed`, at **ERROR** when any destination
  failed. The old summary reported `swept`/`groups`/`written` and no failure count, so a sweep
  that wrote two destinations of three read as a success in every field it had.
- **`sweep_id`** as baggage *and* prepended to every CloudWatch line.

## What changed from earlier specs?

`cpcommon.observability` gains **`stamp(**fields)`**, and `_stamp_verb` / `_stamp_request_id` now
delegate to it — one guarded baggage path instead of three.

It was added here rather than in SPEC-130 because this spec is what surfaced the gap: FR-007 needs
an invocation-scoped join key on the **boundary spans**, which means baggage, and SPEC-130 shipped
no baggage setter. The alternative was importing `log_foundry` at a call site — exactly what
SPEC-130 FR-001's one-door rule exists to prevent. The rule survives by widening the door.

## Two implementation choices worth knowing

**`sweep_id` reaches CloudWatch through a `logging.Filter`, not an edit to each call.** FR-006
forbids removing any existing `logger` call; FR-007 wants the id on *every* line, including those
in `_read_day`/`_append_day` which know nothing about the invocation. A filter satisfies both, and
a line added later gets the id without anyone remembering — the difference between a property and
a convention. It is attached to the root logger, so during a sweep any third-party record routed
through root is prefixed too; in Lambda that is effectively only this function.

**The event count is bounded by day-groups, never by messages.** This function emits into the
queue it drains, so one event per message consumed would give that queue a floor it could never
get below. Guarded by a test that sweeps 20 then 200 messages over the *same* two day-groups and
asserts an identical count, plus a companion asserting the count **does** grow with groups — so
the first cannot pass merely because the count is constant in everything.

## One spec correction

FR-005 illustrated the volume as "roughly `6 + 3G` events per sweep, against a floor of 2".
**Measured 2026-07-23: `6 + 4G`, and 4 on an empty sweep.** The estimate didn't count
`step("receive")`'s own boundary pair or the per-destination entry event, both required by FR-001
and FR-002. The bound's *shape* — O(1) in messages, O(G) in day-groups — is what FR-005 protects
and is unchanged, as is the volume conclusion (a few thousand events a day). The spec text now
carries the measured figures.

## One pre-existing behaviour left alone

An unroutable body counts as **both** `unrouted` and `undated`, because `_partition(None)` falls
back to the sweep clock. That predates this spec, the CloudWatch warning already conflated them,
and "any change to what the sweep does" is out of scope here — recorded rather than silently
fixed, so the two counters are read with it in mind.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1196 passed / 2 skipped (46 in `test_log_sweep.py`).
No infra, IAM, environment variable or SPA change.

Twelve mutations run against a pristine-restore harness, **all killed**: never stamping
`sweep_id`; removing the CloudWatch filter; **adding a per-message emitter**; outcome always at
INFO; never counting `failed`; echoing an unroutable body into the event; removing either `step`;
giving both failure paths the same reason token; narrating an empty sweep; making the delete
warning per-chunk; emitting the CAS retry warning only once.
