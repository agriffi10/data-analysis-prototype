---
type: Decision
title: "The source deletion removes only CONFIRMED-COPIED keys, never a prefix listing (SPEC-187, diverging from SPEC-169)"
description: "The source deletion removes only confirmed-copied keys, re-read per item from the plan, and never lists the source prefix, because an object written after expansion would be lost unrecoverably; the accepted cost is a visible orphan."
---

Recorded here because SPEC-188 and SPEC-189 must honour it and neither is written yet.

SPEC-169's archive rollback lists the source prefix precisely so it catches objects a batch copied
before it died. **Here the same technique loses data.** An object written into the source folder
between expansion and commit — by an upload, a single-file operation, or another plane, none of which
take this plane's lock — was never copied, and a prefix-listing delete would remove it silently and
unrecoverably, with versioning off.

The accepted cost is an **orphan**: it survives, stranded in a folder the user believes moved, which
is visible and recoverable where the alternative is neither.

**It forbids LISTING THE SOURCE PREFIX at deletion time. It does not forbid re-reading the PLAN**,
which is how the keys actually arrive — the transfer engine reports counts and never keys, because a
failed-key list is the unbounded term that breaches the state limit on the Map.

**And the gate is per ITEM, not one boolean over the run.** SPEC-169's is all-or-nothing because
before per-item outcomes the planned set and the confirmed-copied set were identical. They are not
here: a skipped item is planned and not copied, so deleting plan keys would remove the user's source
file while the destination still holds the colliding object that displaced it — a direct,
unrecoverable substitution.

## History

### 2026-08-17

- **Settled:** SPEC-187, diverging from SPEC-169.
