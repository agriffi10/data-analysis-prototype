---
type: Decision
title: "A failure after the copy began says so, and the stage rides inside the caught error"
description: "**A notice for a failure after the run began changing anything must not say try again or nothing changed** — the retry collides with what landed. file-ops and file-send set `$.stage` in a `Begin…` Pass on the only edge into the copy and the deletion; a Catch from there on tests it with an `IsPresent` Choice and `MarkTransferBegun` copies it INTO `$.error`, because the seeds carry the error whole and a Pass reading a key some paths lack is an uncatchable `States.Runtime`. The verbs' own hooks read the same `$.stage`, so the two notices one fault produces share a body."
---

**Decision.** In file-ops and file-send, a whole-request failure that arrives after the run began
changing anything is worded as possibly part-done: *"some of it may have happened … Please look at
the folder before trying again"* (file-ops), *"some recipients may have received part of it. Please
check before sending again"* (file-send), modelled on each plane's timeout sentence. A failure in a
run that changed nothing keeps the sentence it had.

**How the run is marked.** `BeginTransfer` (both planes) and `BeginDeletion` (file-ops) are Pass
states on the only edge into `TransferObjects` and `DeleteSource`, writing `stage: "transfer"`. A
run with nothing to copy — every item refused or a no-op, every recipient refused, or a delete
before its deletion — never passes one. Each plane's state-machine suite holds that those are the
only edges in.

**Two doors read the one mark.**
- The `States.ALL` Catches from `TransferObjects` on route through `ChangesMayHaveBegun`, a Choice
  that tests `$.stage` with `IsPresent` and, when it is set, through `MarkTransferBegun`, which
  writes it into the caught error (`ResultPath: "$.error.stage"`). The failure notifier reads it
  with `cpcommon.errors.transfer_began` and words a fault no verb classified as
  `transfer_interrupted`. A fault in copy-objects reaches the user only this way.
- The verbs' hooks read `$.stage` off their own event with the same function, and map the reasons
  whose body assumes nothing changed — the generic fault, `malformed_event`, `plan_unreadable`,
  `plan_superseded` and delete-source's `forbidden` on file-ops — through the plane's
  `after_transfer_began`.

**Why inside `$.error`.** `RequestFailureSeed` carries `$.error` whole, so a field written into it
reaches the notifier with no seed changed. Having the seed read `$.stage` instead would raise
`States.Runtime` on every path into it that never passed a `Begin…` state. A Choice's `IsPresent`
cannot raise on an absent key. A nested `ResultPath` into an existing object was measured with
`aws stepfunctions test-state`, with and without a `Cause`.

**Why the verb still notifies.** `_verb_already_notified` keeps the deliberate duplicate: a verb's
unexpected fault notifies from the decorator and again from the notifier, because a suppression
that guesses wrong is silent. Once the run is marked, both compose the same message and the same
`{requestId}` payload, so the notifications queue's content-based dedup (per message group, five
minutes) collapses the pair when the notifier runs inside that window. Suppressing the decorator's
notice for these verbs was considered and rejected: it would make the only notice depend on
`NotifyFailure` alone.

**Do NOT** have a seed or a Pass read `$.stage`, decode the stage in ASL, mark the stage on the
Catch alone (a run with nothing to copy reaches the same Catches and would be told some of it may
have happened), or key the wording on the error name: a bare exception name cannot tell a verb
fault from an import failure, which is the trap `_verb_already_notified` already records.

## History

### 2026-11-19

- **Settled:** the 2026-09-26 UI copy audit's owed wording defect, fixed with no spec.
