---
type: Decision
title: "The rollback deletes what is THERE, not what it was told about"
description: "The rollback deletes by listing the run's own archive prefix with no ignore predicate, never from a collector's list; a partial rollback only reports its residue, and a collector that cannot read the export does not roll back."
---

FR-004 says the rollback removes the objects the collector reports as copied. It is implemented as
a `ListObjectsV2` over the archive prefix, and the reading is deliberate. Keys are the unbounded
term — tens of thousands of them cannot ride a 256 KB state — but the listing is also the strictly
better answer: the prefix is `{kind}/{name}/archive/{uuid}/`, this request's alone, so everything
under it was put there by this archive and by nothing else, **including anything a batch copied
before it died and never reported**. A collector-supplied list would omit exactly those. Its
predicate ignores nothing, because the shared paginator's default drops zero-byte placeholders and
hidden segments and both are things this plane deliberately archives.

**A rollback that itself fails partially does not change the outcome.** The property that matters
is that the source is intact, and it is; the residue is billed at the GLACIER 90-day minimum, is
unreachable by the user (the browser has no relationship with that bucket) and is swept by the
7-year expiry. It is reported in the failure notification through its own reason code rather than
retried forever. The same disposition covers a collector that cannot read the export at all: that
is a whole-request terminal with the source untouched, and it does not roll back, because a
collector that cannot read the export cannot say what there is to roll back.

## History

### 2026-08-12

- **Settled:** entered the register.
