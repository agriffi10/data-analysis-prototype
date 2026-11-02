---
type: Decision
title: "One predicate decides who may be destroyed and who may be added (SPEC-205)"
description: "`registry.is_destroyable` alone routes a delete and refuses an add, so never re-derive either side; both routes that free a name clear the union of both rosters and re-read after freeing it."
---

`registry.is_destroyable` is the whole shape of the change: `not everActive and status != "active"`.
The delete verb routes on it, and the guard refusing new members refuses on it. They are complements
of each other, and every revision that wrote them twice moved one without the other — each drift
silent, and each in a different direction. Written once they cannot disagree.

**Do NOT re-derive either side.** Keying the add-guard on `status != "active"` freezes additions on a
was-active-now-`failed` record — a live workspace whose owner is mid-recovery. Keying it on
`not everActive` alone freezes them on any healthy `active` record the backfill has not reached, so a
missed backfill surfaces as adds failing on a healthy workspace. The complement of the destroy
predicate has neither blind spot, and that is the only reason to express it once.

Both routes that free a name — the delete verb's never-active branch and `forget`'s owner path —
**re-read before their loop, clear the UNION of the validator's roster and that fresh one, and re-read
once more after freeing the name**, raising if the record came back. A slot outliving its record is a
principal tag on whatever is created under that name next, because the portal policy is scoped on the
tag *value* and not on any space identity.

## History

### 2026-08-31

- **Settled:** SPEC-205.
