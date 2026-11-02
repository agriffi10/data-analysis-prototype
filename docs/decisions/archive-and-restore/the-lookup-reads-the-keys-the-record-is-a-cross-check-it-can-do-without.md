---
type: Decision
title: "The lookup reads the KEYS; the record is a cross-check it can do without"
description: "A restore derives destinations from the archive prefix's keys with no ignore predicate; `_manifest.json` is excluded by exact root key, may be absent or unreadable, and refuses only when its count disagrees."
---

`inspect-archive` derives every destination by listing the archive prefix and running each key
through `paths.origin_key` — the exact inverse of the writer — because the archived key encodes its
own origin. `_manifest.json` is consulted only to compare counts, and **absent, unreadable and
malformed are all tolerated**: a restore that refused for want of a convenience record would be
precisely the failure mode the self-describing key layout exists to prevent. Only a record that
**disagrees** refuses, which can fire only when something is already wrong.

That tolerance is what made SPEC-169's `test_no_restore_verb_requires_the_manifest` sweep survivable
rather than deleted. The exemption is the layer module alone; a companion test keeps **verbs** out,
including SPEC-171's, so the cross-check has one home and one tested tolerance.

The exclusion is by **exact key at the archive root**, never by basename: a user's own
`reports/_manifest.json` three folders down was archived like any other file and must come back.
Conversely the lookup applies **no ignore predicate at all** — SPEC-169's expansion deliberately
KEEPS zero-byte placeholders and hidden segments, so restoring through a filter the archive did not
write through would silently return less than was taken.

The restore plan goes to the admin bucket and only its **key** rides on the state, for the reason
every artifact on this plane does: at `ARCHIVE_MAX_OBJECTS` the list is tens of megabytes against a
256 KB payload limit, and `States.DataLimitExceeded` is caught by no `Catch` in this machine —
`States.ALL` does not match it and none names it. It is read back with the
same identity check SPEC-169's review added to the copy plan — the key is a pure function of the
request id, so a second run under a reused id overwrites it, and a guard that cleared **that** plan's
destinations would clear a restore for keys this run is not going to write.

## History

### 2026-08-12

- **Settled:** entered the register.
