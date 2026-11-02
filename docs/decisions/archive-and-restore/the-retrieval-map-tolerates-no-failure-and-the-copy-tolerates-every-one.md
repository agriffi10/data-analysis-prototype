---
type: Decision
title: "The retrieval Map tolerates NO failure, and the copy tolerates every one"
description: "**Retrieval is the point of no return.** Its Map tolerates **no** failure (the copy's tolerates 100%): a fault means nothing copied and the archive untouched. What makes that free is that the **verb** tolerates two codes — `RestoreAlreadyInProgress` and `InvalidObjectState` — which is also what keeps the path unconditional on the storage class. **Do not \"harden\" the verb by removing them.**"
---

`ToleratedFailurePercentage` is 0 on `RetrieveObjects` and 100 on `CopyBackObjects`, three states
apart in one machine. Both are right, and the reason is what each Map's failure would cost the
verdict after it.

The COPY must finish whatever happens, because a Map that aborted early leaves the gate after it
unable to tell "failed" from "not attempted" — on the archive arm that gate decides whether a user's
only copy is deleted, and on the restore arm it decides whether the archive is. The RETRIEVAL has no
verdict after it: a genuine fault means nothing was copied and the archive is untouched, so the
cheapest correct answer is to fail the Map Run and let the user re-submit.

**What makes that re-submission free is the two tolerated responses**, and without them the design
would be indefensible. `RestoreAlreadyInProgress` (HTTP 409) is the state the call wanted to bring
about, wearing an error's clothes — raised instead, a redriven execution or any re-submission would
fail on exactly the objects already on their way back, and each retry would bill a second retrieval
for the rest. `InvalidObjectState` is tolerated for a different reason: it is what S3 says when an
object is not in an archival class at all, so tolerating it is what keeps the restore path
**unconditional on `ARCHIVE_STORAGE_CLASS`**. Setting that constant to `GLACIER_IR` leaves this
machinery harmlessly in place rather than requiring a branch, which is how a config change deletes a
code path with nothing to show for it in a diff (SPEC-168's own rule, now load-bearing).

The retrieval is issued through a Distributed Map over the same manifest the copy-back reads, rather
than one verb with a longer timeout, because 20,000 `RestoreObject` calls is not work a single
invocation should be sized for — and the plane already knows how to fan out over a JSONL dataset.
**One manifest serves both Maps**: two would be two things that could disagree with the plan, and
the disagreement would surface as a restore that retrieved one set of objects and copied another,
with every count still agreeing with itself.

## History

### 2026-08-12

- **Settled:** entered the register.
