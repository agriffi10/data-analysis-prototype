---
type: Decision
title: "The source is deleted only while it is UNCHANGED since the plan listed it"
description: "`delete-source` heads every original against the plan's ETag and counts the vault whole before deleting any, all or nothing, and records its verdict create-only so every retry follows it; each copy is pinned to that ETag."
---

**Found by a data-loss audit of the control planes on 2026-09-26.** `delete-source` deleted the
plan's keys by name alone. The commit gate proves every object was copied; it says nothing about
whether the original stood still afterwards, and an archive at the caps copies for minutes to over
an hour. A file written over in that window — re-uploaded by its owner, or by any member of a
shared space — was deleted, leaving the vault's older copy as the only one, with versioning off.
The file-operations move had already closed the same shape with a HEAD-compare before its
deletion; this plane had not.

**The plan records each object's ETag** — from the listing, or the file head that already returned
it — and it is used twice. **Every copy line is pinned to it** (`srcEtag`, sent as
`CopySourceIfMatch`), so the vault holds exactly the planned version, and a file changed before its
copy fails that item and the commit gate rolls the archive back under the existing message. **Then
`delete-source` heads every original before deleting any**, and one that no longer carries the tag
refuses the whole deletion: it removes the vault copy by the rollback's own listing and fails
`source_changed_during_archive` — "N file(s) changed while they were being archived, so nothing was
archived and your files are exactly where they were. Please try again." An entry with **no**
recorded tag refuses the same way without being headed: a plan written before the tag existed
cannot say what the vault holds. An original that heads as **absent** is not a change, because a
Retry re-heads what its first attempt removed.

**And no original is deleted unless the vault holds every planned object at that moment**, counted
by the restore's own fail-closed `archive_is_intact`; a short count removes what is left of the copy
and fails `archive_copy_unconfirmed`, in the existing "we could not confirm that every file had been
copied" sentence.

**The verdict is RECORDED before it is acted on, and every later attempt follows the record** — the
second review's finding, and the one that made the shape above safe to retry. A delete batch that
throttles raises only after every other batch ran, so the state's Retry meets a first attempt that
has already partly acted, and re-deciding let the two paths undo each other in both directions,
each proved against a stateful fake: a deletion that re-decided as a refusal removed the vault copy
of the originals it had already deleted, and a refusal that re-decided as a deletion — the changed
file deleted in between, or a head that failed once — deleted originals whose copy was half gone
and reported success. So `delete-source` writes `source-decision.json` create-only beside the claim
before acting, and a Retry, a lost response or a redrive follows it: a recorded refusal finishes
removing the copy, and a recorded deletion never touches the vault — an original changed since the
verdict is kept, and the run fails `source_delete_incomplete` with the copy intact. **An original
already gone when the verdict is taken forbids a refusal**, since the vault may then hold its only
copy: the verdict is a deletion that keeps whatever changed, and if the vault cannot be counted
whole as well, nothing is decided or touched. The case is a run in flight at the deploy that brought
this in — its plan carries no tags and the old `delete-source` may have deleted part of it before
its Retry landed on the new one — found by a third review in the replay frame.

**All or nothing, and Andrew chose it over keeping per file.** The first shape kept only the
changed originals, deleted the rest and failed `source_delete_incomplete`; a review found that this
deletes into a vault the user cannot find — the receipt that names an archive is written only after
this state succeeds — and that the kept file then blocks a restore of it as a collision. Per file
is right on file operations because each item's outcome reaches the user; here nothing does.

**The residual is the time between an original's head and its batch's delete.** Deciding all or
nothing needs every head before the first delete, so a write landing after its head is not seen:
seconds for an ordinary archive, a few minutes at the object cap. A second sweep just before each
batch would narrow it and was computed against the budget instead of added — two sweeps at the
guard's modelled latency do not fit the Lambda ceiling with this file's headroom rule. The heads cost the
guard's arithmetic, so `delete-source` took the guard's 600s and a test reads it back. **Not a
conditional `DeleteObjects`,** for `focommon.delete`'s reason: whether S3 enforces the ETag on
these buckets is unproven, and a condition serialized and ignored deletes silently.

## History

### 2026-09-26

- **Settled:** entered the register.
