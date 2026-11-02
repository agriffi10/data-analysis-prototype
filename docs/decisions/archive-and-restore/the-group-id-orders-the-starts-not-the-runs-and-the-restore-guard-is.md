---
type: Decision
title: "The group id orders the STARTS, not the runs, and the restore guard is not absolute at the write"
description: "**No restore message may tell the user to destroy anything, or state the archive's condition as fact** — two restores of one archive still both run, and the first to finish sweeps the vault, so the files a message names can be the other run's output and the only copy left. The remediation is **\"move or rename\"**; the one permitted claim is time-scoped (*\"was still complete when this restore stopped\"*) and must be **earned by counting** the prefix. Both rules are enforced over the whole table and the receipt by a test with its own plant corpus, because per-sentence fixes were tried first and each review round found another sentence. **Both rules are DENYLISTS and neither is finished** — a security review walked twelve ordinary instructions (\"destroy\", \"trash\", \"get rid of\", \"send them to the recycle bin\") past the first seven-word version — so the corpus of escapes found so far is kept as a test rather than the coverage being asserted, and widening the list is the cheap side of the trade. Two residuals stand: rule 2 does not catch `destination_occupied_after_retrieval`'s \"will stay ready for a few days\", which invites no deletion; and the rules run over TEMPLATES, so a colliding key rendered into `{sample}` is attacker-chosen text in a safety-critical sentence when the space is shared."
---

> **Repaired 2026-09-20 by SPEC-237; the diagnosis above stands and the consequences it
> describes no longer do.** Every copy-back line is now a conditional write, so no restore overwrites
> anything — not a file the user edited, not a file a sibling restore put back — and the
> unconditional-`CopyObject` sentences below are superseded. One archive id is one run, by a
> create-only claim inspect-source takes after the listing, so the reused-id arm is closed rather
> than narrowed. **What remains true is the overlap itself and what it costs in REPORTS:** two
> restores of one archive still both run, both may send "started" and "restored", and a run whose
> sibling swept the vault first still reports an incomplete restore or fails as
> `archive_object_unreadable`. What no longer follows is data loss, because no message tells the
> user to delete anything and none calls the archive complete without counting the prefix.

Found 2026-09-15, auditing the module README's claim that two archives from one space, and two
restores of one archive, serialize. Neither does, and the same audit found the guard's own residual
understated.

**The premise was false.** This plane's Pipe starts its Standard machine `FIRE_AND_FORGET`, as every
plane's does — AWS allows a Standard workflow no other mode — and the message leaves the queue once
`StartExecution` returns, after which the Pipe sends the group's next batch. A `MessageGroupId`
therefore orders the starts, and a failed start holds the next one back until its retries run out;
nothing stops a second run beginning while the first is still going. The table-builder refresh and
file-ops each hold a lock for exactly this, and file-ops' live check watched two runs in one group
overlap on a Pipe identical to this plane's. **This plane's own live run already had**: two restores
of one archive submitted 25 s apart on 2026-09-09, where the second failed after its poll met the
vault the first had swept (`docs/testing/sessions.md`, *The archive and restore, run under §4.11's
approval gate*). The archive specs gave serialization as the reason for
both keys and this plane's prose carried it forward, while `arcommon.plan` already keyed each
manifest by execution so that two overlapping executions of one request could not clobber each
other.

**What overlap does, arm by arm:**

- **Two archives from one space, different ids: safe, and the commit gate is why.** Each run deletes
  only its own plan's keys, only once every one is confirmed under its own `{uuid}` prefix, and its
  rollback lists only that prefix. An overlapping object is either archived twice — two receipts,
  two `GLACIER` copies at the 90-day minimum — or deleted by one run before the other copies it,
  which fails the other's copy and rolls it back with nothing deleted. `DeleteObjects` reports a key
  the other run already removed as deleted, so neither run fails on the other's work.
- **One archive id twice, past the dedup window: unrecoverable, and already recorded.** [The reused-id
  entry](the-request-id-is-browser-supplied-so-a-reused-one-is-refused-twice-over.md) says
  `request_id_reused` narrows it and does not close it. What it did not say is that the queue does
  not close it either.
- **Two restores of one archive: not billed twice, and not safe.** S3 answers the second
  `RestoreObject` with `RestoreAlreadyInProgress` while the first is in flight, and bills it as a GET
  once the first has finished, so the retrieval is spent once. Both runs pass the first guard, since
  nothing lands for hours, and each then polls on its own five-minute clock, so what follows depends
  on timing. The first to see the retrieval finish can restore a small archive and sweep the vault
  before the other polls again, and that poll then heads a missing object and fails as
  `archive_object_unreadable`, telling the user to contact an administrator. A second guard pass that
  runs after the other run has copied a file back refuses as occupied, over the restore's own files.
  If both second passes run before any copy lands, both copy back with an unconditional `CopyObject`,
  and if one sweeps the vault while the other is still copying, the other reports
  `restore_incomplete` over a restore that fully landed and rewrites the receipt to say the archive
  is intact, when it is gone — and the message tells the user to delete the files that came back
  and request again, which would destroy the only copy. A file the user edits after the first run
  restored it is overwritten silently if the second run copies it while the vault copy still exists.

**The guard's own residual was understated, with no overlap needed.** The second pass heads every
destination once, before the copy-back Map, and the Map then runs for as long as the archive copy it
mirrors. So the guard holds when the copy-back STARTS rather than at every write, and the residual
the [guard-runs-twice entry](the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee.md)
called seconds is most of that Map for an object copied late in it: a file the user re-creates at a
path not yet restored is overwritten by a single restore.

**Decided 2026-09-15 (Andrew): repair it with conditional writes, not a lock.** `CopyObject` and
`CompleteMultipartUpload` both take `If-None-Match: *` on the destination and answer `412` when the
key exists, which would make the guard hold at every write, against the user and a second restore
alike; and a create-only claim on the archive id would close the reused-id race that
`assert_archive_unused` only narrows. A per-archive restore lock was weighed and not chosen: it stops
the overlap and its misleading reports, but it brings acquire and release states and a staleness
limit above the 12-hour ceiling, and it leaves the single-restore window open. The overlapping
restore's duplicate and false-failure reports are the accepted cost — **except the incomplete
report's instruction to delete the files that came back**, which a spec review found would destroy
the only copy once another run has swept the vault. That one is not accepted (Andrew, the same day):
SPEC-237 holds every restore message to two rules, and counts the vault before any message calls the
archive complete.

**What the repair cost, measured rather than predicted.** The conditional write is one header on
two operations, and the work was in what a refusal MEANS: a batch re-raises one item's transient
fault after every copy has settled, so its retry meets its own earlier writes and every one of
them is refused. Read as "occupied", a retried restore would have reported the files it had just
put back as being in the way. So a `412` is settled by heading both objects and comparing ETag,
length, content type and user metadata — the run's own write always matches on both copy paths,
because the single copy carries metadata under `MetadataDirective` and the multipart create
re-states it, and every bucket here is `AES256`, which is what makes an ETag content-derived.
Under SSE-KMS none of this would work. A `409` is transient on both paths, and the multipart half
is safe for a reason worth writing down: AWS says a conflict there requires re-initiating the
upload and re-copying every part, and the engine satisfies that by construction, because it aborts
and raises so the batch's own retry runs `CreateMultipartUpload` again.

**Both restore-message rules — no instruction to destroy anything, and no statement of the archive's condition as fact — are enforced over the whole table and the receipt by a test with its own plant corpus**, because per-sentence fixes were tried first and each review round found another sentence. **Both rules are DENYLISTS and neither is finished** — a security review walked twelve ordinary instructions ("destroy", "trash", "get rid of", "send them to the recycle bin") past the first seven-word version — so the corpus of escapes found so far is kept as a test rather than the coverage being asserted, and widening the list is the cheap side of the trade. Two residuals stand: the condition rule does not catch `destination_occupied_after_retrieval`'s "will stay ready for a few days", which invites no deletion; and the rules run over TEMPLATES, so a colliding key rendered into `{sample}` is attacker-chosen text in a safety-critical sentence when the space is shared.

## History

### 2026-09-20

- **Changed:** SPEC-237 repaired it: every copy-back line is a conditional write and a create-only claim makes one archive id one run, so overlapping restores now cost duplicate or false reports rather than data.

### 2026-09-15

- **Settled:** entered the register.
