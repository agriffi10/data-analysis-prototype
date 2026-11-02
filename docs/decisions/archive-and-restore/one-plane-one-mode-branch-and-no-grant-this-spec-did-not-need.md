---
type: Decision
title: "One plane, one `mode` branch, and no grant this spec did not need"
description: "One machine serves archive and restore, branching on `mode`; every `Choice` comparison is guarded with `IsPresent`, and its `Default` seeds a reason code, never `TerminalError`."
---

**ONE machine serves both archive and restore**, branching on `mode` — SPEC-143's create/refresh
branch on the table-builder is the precedent, not a sixth module: the two verbs share the bucket,
the execution role, the key layout and the receipt, and a restore is meaningless without the archive
that produced it. The `Choice` guards **every** comparison with `IsPresent`, per choice rather than
once: a `Choice` on an absent path raises uncatchable `States.Runtime` and `Default` does not cover
it. Its `Default` seeds a **reason code**, never `TerminalError` — notify-failure treats that one
name as evidence a verb's decorator already notified, so a seed wearing it would be silently
suppressed (the recorded `DiffMissingSeed` rule).

**The execution role holds no S3 grant on any data bucket at this stage, and the restraint matters
more here than on any other plane.** Archiving is the only operation in this repo that deletes a
user's data as a side effect of a copy. Every other plane's execution role carries a blanket
`Deny s3:DeleteObject` from its first apply and has that be an enforced property forever; **this one
cannot**, because SPEC-169 has to grant `DeleteObject` on the source buckets. So the property that
replaces it belongs to the spec that grants it — scoped to the space prefixes, never reaching
`athenaresults/`, `user_settings/` or any `DO_NOT_DELETE.txt`, with the commit gate in front of it —
and granting nothing today keeps that an explicit decision rather than an inheritance.

**No `TimeoutSeconds` yet, deliberately.** Nothing in this machine waits: no Map, no manifest, no
copy, no poll loop. A ceiling does **not** on its own reach `NotifyFailure` — AWS catchers cover
Task, Parallel and Map states but not top-level execution failures — so it must ship WITH an
EventBridge `TIMED_OUT` rule or it is SPEC-152 satisfied on paper and silent in practice. Two tests
are tripwires on exactly that: one fails the moment a `Map`, `Wait` or `Parallel` appears, the other
the moment notify-failure grows a second door without one.

## History

### 2026-08-12

- **Settled:** entered the register.
