---
type: Decision
title: "The lock protocol is `cpcommon`'s, extracted ahead of its second consumer (SPEC-187)"
description: "**The lock protocol lives once, in `cpcommon`**, extracted ahead of its second consumer rather than copied. **Locks are objects claimed under ETag CAS**, released by **overwriting**: with `DeleteObject` denied, \"free\" is a state rather than an absence. The holder is the **execution ARN**, because a request id is whatever the caller sent, so two executions can carry the same one. A redelivered message should not be one of them: reusing an execution name was measured (`../infra/info/control-plane-shape.md`) to return the original run while it is going and `ExecutionAlreadyExists` once it has closed. That a redelivery reuses its name is inferred from the Pipe's v5 UUIDs, not proven, so no lock relies on it."
---

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

**Locks are objects claimed under ETag CAS**, released by overwriting: with `DeleteObject` denied, "free" is a state rather than an absence. The holder is the execution ARN, because a request id is whatever the caller sent, so two executions can carry the same one. That a redelivery reuses its execution name is inferred from the Pipe's v5 UUIDs, not proven, so no lock relies on it.

**File operations are synchronous iff exactly one file.** The per-space lock's loser waits, and a cross-space operation takes both locks in digest order or neither. The space root is refused as an item. The collision unit is the derived destination key, where a protected destination is judged as well as at the prefix, since an item's name can land in a locked folder, and every planned key is judged against the role's any-depth write Deny before the transfer, as the source keys are against its delete Deny. A 403 counts as occupied, and the deletion takes confirmed plan keys, because a prefix listing orphans an uncopied object.

## History

### 2026-08-17

- **Settled:** SPEC-187.
