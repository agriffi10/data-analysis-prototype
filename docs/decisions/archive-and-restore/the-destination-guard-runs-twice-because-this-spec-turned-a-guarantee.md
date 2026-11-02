---
type: Decision
title: "The destination guard runs TWICE, because this spec turned a guarantee into a promise"
description: "**It runs TWICE**, and the second pass is the spec correcting itself: those billed hours are spent telling the user a restore is in flight, so re-creating a file meanwhile is the ordinary case — and the copy-back would have overwritten it, reported success and swept the vault."
---

SPEC-170's rule is absolute: **any** occupied destination refuses the **whole** restore, because S3
has no move and no rename, versioning is off, and a copy over a file the user re-created destroys it
with no trace. One check was sufficient while the guard and the copy were seconds apart — the
residual TOCTOU was an unlikely double-submit, the same one table-share and file-send carry.

**SPEC-171 put three to five BILLED HOURS between the check and the write, and spent them telling
the user a restore was in flight.** That is not the same window wearing a bigger number. It is a
window the plane itself opens and then invites the user to act inside: the receipt marker exists
precisely so somebody waiting hours knows something is happening, and somebody who knows their
restore is hours away goes and works in their own space. Re-creating a file there is the ordinary
case the guard was written for, arriving late — and the copy-back would have overwritten it,
reported **success**, and swept the vault.

`ReCheckDestinationClear` invokes the same verb over the same plan immediately before the copy-back.
It costs one round of heads (the guard's own 20,000-at-8 bound, ~250 s worst case) against a run
that has already waited hours, and it is what makes "any occupied destination refuses the whole
restore" true ~~at the moment of the WRITE~~ **— superseded 2026-09-15: when the copy-back STARTS,
which is not every write ([the group id entry](the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md)) —**
rather than only at the moment of the PROMISE.

Two details are decisions rather than mechanics. **The refusal is worded differently**, because the
two passes leave the user somewhere different: before the retrieval nothing has been spent, and
after it the objects are out of Glacier and stay ready for `RESTORE_AVAILABILITY_DAYS`, so a prompt
second attempt costs neither the wait nor the bill again — a fact the user needs and cannot possibly
infer from "some files are already there". And **the stage is SEEDED BY THE MACHINE**, never
inferred from what else is on the state, for the same reason `update-receipt`'s three stages are:
"the retrieval has not run" and "the retrieval reported nothing" look identical from inside a
handler, and getting that wrong tells a user their retrieval is still warm when it was never made.

It **narrows rather than closes**, as table-share's and file-send's guards do — two concurrent
writers can still land a file between the second head and the copy. The difference in kind is what
matters: seconds of overlap is a double-submit, and hours is the user acting on a message this plane
sent them. **— Superseded 2026-09-15: the residual is not seconds.** The heads run once, before a
copy-back Map that runs for as long as the archive copy it mirrors, so the window before a late
object's write is most of that Map; and a second restore of the same archive runs beside this one,
because the FIFO group orders only the starts. **— And superseded again 2026-09-20: there is no
residual at the write.** Every copy-back line carries `ifAbsent`, so S3 refuses the write itself
whenever anything is at the key, however late it arrived. What these two passes still buy that the
condition cannot is the WHOLE-request refusal: the condition protects one object at a time and
reports the rest as landed, where a guard pass names the colliding paths and refuses before the
user has been told a restore is under way.
[The group id entry](the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md)
has the repair.

## History

### 2026-09-20

- **Changed:** No residual remains at the write, because every copy-back line is conditional; the two passes still provide the whole-request refusal.

### 2026-09-15

- **Changed:** The second pass holds when the copy-back starts rather than at every write, and its residual is most of the Map rather than seconds.

### 2026-08-12

- **Settled:** entered the register.
