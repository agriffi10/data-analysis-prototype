---
type: Decision
title: "The restore's gate is the commit gate's MIRROR IMAGE, not its twin"
description: "A restore's failure arm deletes nothing, neither landed objects nor the archive, and no path from it reaches `DeleteArchived`; a failed vault sweep only flags `cleanupIncomplete` on a successful run."
---

Archiving's gate protects the SOURCE: nothing is deleted unless every object was confirmed copied.
The restore's gate looks identical — one boolean from one collector, `IsPresent`-guarded, failing
closed — and protects the ARCHIVE, for a reason that runs the other way.

**A partial restore cannot be rolled back.** The user's space already holds some of their own data,
and deleting it to make the operation atomic would destroy the very thing the restore was for. So
the failure arm deletes **nothing** — not the objects that landed, not the archive — and the archive
it keeps is then the only complete copy in existence. A restore that half succeeded and then deleted
its own source would be unrecoverable, versioning being off. A graph walk asserts no path from that
arm reaches `DeleteArchived`, the same way SPEC-169's walk asserts no path from its rollback reaches
`DeleteSource`.

`restore_incomplete` therefore has to say **three** things, and the third is the one an author would
leave out: how many objects came back, that the archive is intact and still restorable under the
same id, and that **requesting it again will report the files that DID land**. **— Superseded
2026-09-20: the second of the three may not be said as a fact.** A sibling restore can sweep the
vault after the message is sent, so the body now says the archive "was still complete when this
restore stopped" and only when a count of the prefix earned it; where the count does not add up it
becomes `restore_archive_cleared`, which claims nothing. The third is unchanged except that its
remediation is "move or rename" rather than "delete". Without that last
sentence the obvious next action produces a `destination_occupied` refusal that reads like a new bug
on top of the old one. It is also the one body on this plane that describes a partial outcome, so
`test_no_body_promises_a_partial_outcome_except_the_one_that_is` gained a named exemption
set rather than a skipped assertion — a second body drifting into partial wording has to be
argued for.

**The vault sweep's failure does NOT fail the run, where the source deletion's does.** Same
algorithm, opposite consequence: a half-deleted source means a user told their archive completed
while their files are still half there, and a half-swept vault costs storage in a bucket the browser
cannot reach that the 7-year expiry reclaims. So it is a `cleanupIncomplete` flag on a *successful*
run and the user is not told at all. Deleting inside the `GLACIER` 90-day minimum is an
early-deletion fee brought forward, not a defect — recorded because a later cost investigation would
otherwise read it as one.

## History

### 2026-09-20

- **Changed:** `restore_incomplete` may no longer state the archive is intact as fact: it says "was still complete when this restore stopped" only when a count earned it, and its remediation became "move or rename".

### 2026-08-12

- **Settled:** entered the register.
