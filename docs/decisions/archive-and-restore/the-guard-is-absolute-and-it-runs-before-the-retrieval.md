---
type: Decision
title: "The guard is absolute, and it runs before the retrieval"
description: "**The restore guard is ABSOLUTE and runs before the bill:** any occupied destination refuses the **whole** restore, and a **403 counts as occupied**. **It holds at the CHECK and at every WRITE**, by two mechanisms that are not redundant: the guard refuses the whole restore up front with the colliding paths named, and every copy-back line is a **conditional write**, so a file arriving while the Map runs is left alone one object at a time. A refused write is **resolved by comparing destination against source**, never read as occupied outright — a batch retrying after a transient fault meets its own earlier writes, and reading those as collisions would report the files it just restored as being in the way. **Every test of the condition runs against a fake**; the deployed behaviour is owed (`docs/testing/owed.md`, *the conditional copy-back*). **The comparison rests on an ETag, which under `AES256` is an MD5** — so a co-member of a shared space who knows an archived object's bytes could in principle write a same-length MD5 collision at the destination and have the item counted copied and the vault swept. It needs a chosen-prefix collision, the target's content, and write access to the path — which already allows overwriting the file directly — so what the attack adds is the sweep. Not repaired here; the repair is to prefer `ChecksumSHA256` when the object carries one."
---

S3 has no move and no rename, so a restore is a copy and a copy overwrites. If the user has
re-created `reports/q1.csv` since archiving it, restoring on top destroys the newer file with no
trace and no versioning to recover from. So **any** occupied destination refuses the **whole**
restore: no skip, no overwrite, no merge and no "restore what fits". Partial restores around an
obstacle were considered and rejected — they leave a folder holding two generations of the same
data with nothing recording which is which, and the user cannot tell by looking.

**A `403` counts as OCCUPIED.** A key this role cannot head is a key it must not overwrite, and on
these buckets that is live rather than hypothetical: the execution role's own policy Denies it
beneath `athenaresults/`, `user_settings/` and `archive/`. Reading an ambiguous answer as "clear" is
the one mistake here that ends in data loss, so the guard fails closed on anything that is not a
proven 404 — including an error carrying no status at all.

**And it runs before any `RestoreObject`, which is why the arc splits at exactly this state.**
Glacier retrieval is billed and irreversible once initiated. Everything in SPEC-170 is verifiable in
seconds; everything in SPEC-171 takes 3–5 hours and cannot be cancelled. A guard on the far side
would report the same refusal and charge the user for the privilege. The property is asserted by
walking the ASL graph from the guard's failure branch and requiring that **everything** reachable
from it is the failure path itself — not by asserting "no path to a retrieval state", which passes
vacuously while no retrieval state exists and would go on passing forever.

The refusal names a **bounded sample** because the guard **short-circuits**: an archive of 200,000
objects must not issue 200,000 heads to report a conflict found in the first hundred. Having
short-circuited, it genuinely does not know the total — so the message says there may be more.
Implying the sample was exhaustive would send the user round the clear-and-retry loop once per
hidden collision. The sampled keys render **relative to the space root**, so the user reads a path
they recognise from the file browser.

**Every test of the conditional copy-back runs against a fake**; the deployed behaviour is owed (`docs/testing/owed.md`, *the conditional copy-back*). **The comparison that settles a refused write rests on an ETag, which under `AES256` is an MD5** — so a co-member of a shared space who knows an archived object's bytes could in principle write a same-length MD5 collision at the destination and have the item counted copied and the vault swept. It needs a chosen-prefix collision, the target's content, and write access to the path — which already allows overwriting the file directly — so what the attack adds is the sweep. Not repaired here; the repair is to prefer `ChecksumSHA256` when the object carries one.

## History

### 2026-08-12

- **Settled:** entered the register.
