---
type: Decision
title: "`GLACIER`, and why the other two were rejected"
description: "The vault class is `GLACIER` Flexible Retrieval, set once in `ARCHIVE_STORAGE_CLASS`; no code may branch on it, a restore is `RestoreObject`, a wait and a copy, and the confirm dialog must state the 90-day minimum."
---

`arcommon.config.ARCHIVE_STORAGE_CLASS` is the single definition, and it determines the shape of
every spec after it. **`GLACIER` (Flexible Retrieval) is not readable**: a `CopyObject` whose source
is in it fails `InvalidObjectState`, so a restore is not a copy — it is `RestoreObject`, a 3-5 hour
wait, and *then* a copy. That is why SPEC-171 grows a `Wait`/poll loop no other plane in this repo
has, and why 170 must land before it.

**`GLACIER_IR` was rejected precisely because it would have removed all of that.** It is readable in
real time, which deletes the restore machinery entirely — and it is the most expensive Glacier
class. An archive the user can still read on demand is not an archive; it is data moved to a cheaper
bucket, and the feature's whole premise is that putting something away is deliberate and reversing
it is slow. **`DEEP_ARCHIVE` was rejected the other way**: ~4x cheaper again, but 12-48 hours to
restore and a **180-day** minimum, which turns an ordinary "I need that back" into a two-day wait.

The **90-day minimum storage duration is a property of the class, not a defect**, and the user has
to be told: an object archived on Monday and restored the following week is still billed for 90
days. SPEC-172's confirm dialog says so in user-facing wording. *(For a while it did not: the
sentence was lost from the dialog and SPEC-250 put it back, beside where the data goes and how a
restore brings it back.)*

The restore machinery is **unconditional** whatever the constant is set to — a class that needs no
restore still tolerates one being requested. A test forbids any branch on the constant anywhere on
the plane, because making the machinery conditional is how a config change silently deletes a code
path with nothing in the diff to show for it.

## History

### 2026-08-12

- **Settled:** entered the register.
