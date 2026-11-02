---
type: Decision
title: "A timeout does not stop a running verb, so the timeout door claims the deletion verdict"
description: "**A timeout does not stop a running verb.** The ceiling's door claims `delete-source`'s verdict create-only as `stopped` before it tells anyone \"nothing was deleted\", so a `delete-source` still running past the ceiling deletes nothing; a verdict to delete, or one that cannot be read, gets a sentence true either way."
---

**Found on 2026-09-26 by a replay-frame review during the control-plane data-loss audit.** The
archive's EventBridge `TIMED_OUT` door always sent `archive_timed_out` — "Nothing was deleted and
your files are exactly where they were" — on the reasoning above that deletion is downstream of the
commit gate. Nothing stopped the 43,200 s ceiling landing while `delete-source` ran, or while
`write-receipt` ran after it: originals partly or wholly gone, no receipt, and a message saying
nothing was deleted.

**Reading the verdict record was the suggested fix, and it leaves a race.** Step Functions stops
waiting at the ceiling, but Lambda has no way to cancel an invocation, so a `delete-source` already
running goes on for up to its own 600 s. Caught while it is still heading originals, it has
recorded nothing: the door reads "no verdict" within seconds and promises, and the invocation then
records a deletion and acts on it. So the door does not read the record — it **claims** it, a
create-only `stopped` through `plan.record_source_decision`, and S3 decides which writer came first.
`delete-source` follows `stopped` at either of its reads by deleting no original, removing nothing
from the vault and failing `archive_timed_out`, the door's own sentence. A `delete-source` that
records verdicts but predates `stopped` reads the record as unreadable and refuses to decide, so the
order functions update in within one deploy cannot delete over it. The claim is taken before the
door checks whether anyone can be told, because it protects the originals either way — as long as
the execution's input, and so its id, can be read at all.

**What each outcome tells the user, and Andrew chose all three.** No verdict (claimed as `stopped`),
`refuse` or `unconfirmed` keeps `archive_timed_out`, which the record now makes true. `delete` gets
`archive_timed_out_may_have_deleted`: the files "may already be archived and no longer in your
space", "Nothing has been lost", and the archive id to quote to an administrator — the id is the
archive's name, and the receipt that would carry it may never have been written. "Nothing has been
lost" holds because `delete-source` deletes only after counting the vault whole and only originals
that carried the planned tag when it headed them — short of the head-to-delete residual the entry
above names — and a timeout runs no rollback that could remove the vault. **A
claim or read that fails gets the same hedged sentence** rather than the promise, because the promise
is the one sentence that can then be false. A restore claims nothing: it deletes no original.

**The key comes from the VALIDATED id, not the raw body's.** `validate-authorize` lowercases the
browser's id before any verb keys on it, and the door reads the Pipe's raw record — so an id sent in
capitals would have found no verdict under its own spelling and promised. The door runs it through
`paths.validated_request_id`, and an id that fails that check was refused before any verb ran.

**One residual, and it closes on its own.** A run whose `delete-source` ran before the verdict record
was deployed recorded nothing, so if it then times out the door finds no verdict and promises — and
an invocation of that older code still running when the door claims ignores the claim. The ceiling
bounds both to twelve hours after the record's deploy.

**Not repaired here: results-conversion's timeout sentence** also promises ("Nothing was saved")
from outside the run while its convert verb can outlive the ceiling. It is left because that ceiling
is sized above the longest path a test computes, so reaching it at all means that arithmetic was
wrong.

## History

### 2026-09-26

- **Settled:** entered the register.
