---
type: Decision
title: "A per-table lock serializes refresh, because the catalog cannot (SPEC-157)"
description: "Refreshes of one table are serialized by a lock object in the admin bucket, claimed under ETag CAS and held by the execution ARN, never the request id; the loser is refused with a notification, and release overwrites the object rather than deleting it."
---

Two refreshes of one table could overlap. `MessageGroupId` is the target database, so SQS serializes
*delivery* per database — but the Pipe starts the machine `FIRE_AND_FORGET`, so **delivery ordering is
not execution ordering**. SPEC-149 reduced the damage to last-write-wins between two definitions and
could not close it, because **Glue offers no compare-and-set on `UpdateTable`**.

**The serialization is a lock object in the admin bucket, claimed under ETag CAS**, one per
`{database}/{table}` under `locks/table-builder/`. The loser is **refused, not queued**: a held lock
means a refresh of that table is already running *against the same files*, so a queued run would pay a
full `inspect-source` to compute an identical definition. The refusal is a `TerminalError` through the
plane's existing notify path — the refusal **is** the notification.

**Two rejected alternatives, recorded so they are not re-proposed.** `REQUEST_RESPONSE` on the Pipe is
**impossible, not merely undesirable**: botocore's `pipes` model states that it "is not supported for
STANDARD state machine workflows", so making the Pipe synchronous means converting the machine to
EXPRESS — rejected on two independent grounds, its 5-minute ceiling against `inspect-source`, and its
**at-least-once** semantics, which would introduce the duplicate executions this spec exists to
prevent. A finer `MessageGroupId` would change nothing, because delivery is already ordered.

> **The PROTOCOL moved to `cpcommon.lock` (SPEC-187).** Everything below still describes what the
> table-builder's lock does and why; what changed is where the code lives. The three-way acquire, the
> 412/409 mapping, the staleness and future-date rules, the re-claim and the release-by-overwrite are
> now shared, and `tbcommon.table_lock` binds them to this plane's key, thresholds and wording. Its two
> suites were not rewritten — the protocol moved out from under them — which is what makes the move
> provably behaviour-preserving.

**The lock releases by OVERWRITING, and that is forced rather than chosen.** The execution role
carries an explicit `Deny` on `s3:DeleteObject` for the whole admin bucket, which SPEC-149 kept when it
removed `glue:DeleteTable`. Releasing by deletion would mean amending a standing safety property for an
implementation convenience, so **"free" is a state of the object, not its absence**.

**The holder is the EXECUTION ARN and must never be the request id.** A request id is whatever the
caller sent, and the queue deduplicates it for only five minutes, so two executions can carry the same
id — and the re-entrancy branch (which exists so an SFN Task retry does not self-refuse) would hand the
lock to both, silently. A redelivered message should not be the road to that second execution:
reusing an execution name [was measured](../../../infra/modules/control-plane/README.md#a-redelivered-message-is-not-a-re-run)
to return the original ARN while that run is going and to fail with `ExecutionAlreadyExists` once it
has closed, so a redelivery that reuses its name is either swallowed or fails its start, and a start
that keeps failing ends on the request DLQ. That the Pipe reuses the name for a redelivered message is
inferred from its v5 UUIDs rather than proven, so the lock does not rely on it. The ARN reaches the verb through a `Pass` state, **not** the task's own
`Parameters`: reading `$$` there means building an object, which wraps the payload, and every
notification path in this plane reads the request at the **top level** of the event.

**A lock is stealable only because executions are bounded, so the bound came first.** The machine had
no `TimeoutSeconds` — a Standard execution may run for a year, against which no age threshold is
defensible. It is a **top-level field of the ASL**, not a resource argument (`aws_sfn_state_machine`
has none; `tofu validate` rejects it). A malformed body, an unparseable stamp and a **future-dated**
one are all stolen: a timestamp that cannot be true is no evidence a refresh is running, and the
alternative is a table that can never be refreshed again.

**The freshness guard narrows the residual window and does not close it.** `apply-refresh` compares the
`UpdateTime` captured at the start of the run against its own pre-write read. **A moved stamp is not by
itself another writer** — the state retries on faults that can fire *after* the update committed, so
the retry re-reads a table whose stamp this run moved; judging on the stamp alone failed a run that had
already succeeded and sent the user a notification contradicting the success one. What the run writes
settles it: a live table already carrying exactly those columns, types and projection properties is
one the update cannot change. **It is everything the write owns, not the column names** — a name-only
check, found by an audit on 2026-09-26, read any moved stamp as this run's own whenever a refresh only
retyped, and wrote the loaded projection back over a range the user had widened meanwhile.

Full account: `docs/spec-delivery/SPEC-157-serialize-concurrent-table-refresh.md`.

## History

### 2026-09-26

- **Changed:** The freshness guard compares everything the write owns, after a name-only check overwrote a range the user had widened.

### 2026-08-05

- **Settled:** SPEC-157.
