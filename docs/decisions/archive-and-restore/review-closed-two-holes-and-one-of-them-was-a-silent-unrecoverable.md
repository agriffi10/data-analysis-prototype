---
type: Decision
title: "Review closed two holes, and one of them was a silent, unrecoverable deletion"
description: "A user's file named `_manifest.json` at the space root is refused whole as `reserved_object_name`, and only at that exact key; the guard stops at the round that finds its first collision."
---

**A user's own file at the SPACE ROOT called `_manifest.json` archived onto this plane's own
record.** An object's archive key is `{archivePrefix}{relKey}` and the record's is
`{archivePrefix}_manifest.json`, so the two collide for exactly one relative key. Nothing upstream
caught it: `assert_not_reserved` refuses selecting the space root as a *folder*, but naming that
file directly passes containment, the reserved-root rule and the marker rule. The copy would land,
`write-manifest` would **overwrite** it with the record, `delete-source` would then delete the
user's original — the vault has versioning off — and the run would report **success**. The archive
was also permanently unrestorable: the restore excludes that key as the record, counts one object
fewer than the record claims, and refuses `restore_archive_incomplete` for everything archived
beside it; archived alone, it restores as `archive_not_found` against a receipt the user is holding.

It is refused up front (`reserved_object_name`), for the whole request, rather than excluded —
SPEC-165's direction, because dropping it silently would archive everything else and delete the one
object it could not carry. Moving the record out of the archive prefix would remove the class
rather than the instance, and was **rejected**: FR-003 AC2 specifies the exclusion, so the record
living at the archive root is the spec's own model, and a sibling key would make the exclusion test
assert nothing. The rule is exactly as narrow as the collision — `reports/_manifest.json` three
folders down has a different relative key, collides with nothing, and archives and restores like any
other file.

**The guard did not short-circuit in the case FR-004 AC3 names.** The sample check sat after a full
round *and* required `RESTORE_CONFLICT_SAMPLE` collisions before returning — so fewer than five
meant no short-circuit at all. Measured: 20,000 heads to report a collision at index 3, when one
re-created file is the likeliest real conflict there is. It now stops at the round that finds the
first one. **The test that named the property could not fail**: its fixture used 64 *consecutive*
collisions, which fills the sample inside the first round, so it passed against the broken code — a
fixture that makes an assertion trivially true, which is the shape SPEC-163 records.

Two smaller ones, both about the wording rather than the data. A malformed **restore** was worded
as an archive failure, because `mode` came from the contract check's *return* and every refusal it
raises happens before that — so the wording mode is now seeded from the untrusted body first, which
is safe because the value selects between two fixed prefixes and reaches nothing else. And the
EventBridge `TIMED_OUT` door never passed `mode` at all: unreachable today, but SPEC-171's 3-5 hour
retrieval makes the timeout *predominantly* a restore event, so it now reads the mode out of the
same raw body the actor comes from and `restore_timed_out` ships beside `archive_timed_out` —
because what a timeout may PROMISE differs by arm, and "nothing was deleted and your files are
exactly where they were" says nothing true about a restore.

## History

### 2026-08-12

- **Settled:** entered the register.
