---
type: Decision
title: "Completion is the `Restore` header, and an ABSENT header is a failure"
description: "Retrieval completion is read only from the `Restore` header, and no header on a Glacier-class object is a failure rather than a wait; poll progress stays in S3 and the iteration cap lives in Python."
---

Nothing observable about an archived object changes when its retrieval completes. It stays
`GLACIER`; what appears beside it is a temporary readable copy that the `Restore` response header
describes. So the poll reads that header and nothing else, and there are three answers rather than
two:

- `ongoing-request="false"` — the temporary copy exists and the object can be copied.
- `ongoing-request="true"` — S3 is still working.
- **no header at all, on an object still in a Glacier class — nothing ever asked for this object.**

The third is why this is a module with its own suite rather than a boolean. Read as "not yet" it
would burn every one of the 84 poll iterations, wait seven hours, and then report `restore_timed_out`
for something that was never going to complete — a wrong cause on a run the user has been watching.
The mirror case matters too: an absent header on a NON-Glacier object means the object needs no
retrieval, so treating a missing header as a failure everywhere would refuse a restore of something
already readable.

**The poll samples, and its progress is an S3 pointer.** A per-object status list on the state is the
256 KB failure whose overflow escapes every `Catch` here (`States.ALL` does not match
`States.DataLimitExceeded` and none names it) — which on this plane is a run that told the user
nothing at all — so the record lives beside the plan in the admin bucket and only scalars ride. The
paging rule has two halves that are easy to conflate: `RESTORE_POLL_PAGE` is the granularity progress
is **recorded** at, and the invocation's own bound is the whole plan. One page per `Wait` was the
obvious reading and is wrong: every object was requested at once at one tier, so they finish
together, and sweeping 20,000 objects a page at a time would add twenty five-minute waits — over an
hour and a half — *after* the retrieval had already completed.

**S3 Event Notifications (`s3:ObjectRestore:Completed`) were rejected as the completion signal**, and
not because polling is nicer. They would need bucket notification configuration covering every
archive prefix, a correlation store keyed by object so an arriving event could be attributed to the
run that asked for it, and a second delivery path with its own at-least-once semantics — to replace
a poll inside a machine that is already sitting still for hours, and that the plane already knows how
to write. The poll costs one Lambda invocation every five minutes.

**The iteration cap lives in Python and not in the ASL `Choice`.** `poll-restore` computes
`exhausted` itself and the Choice reads a boolean, because a literal in the rendered machine plus a
constant in `config` is two homes for one number — and they would only ever disagree on a restore
that was already going badly.

## History

### 2026-08-12

- **Settled:** entered the register.
