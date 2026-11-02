---
type: Decision
title: "The collision unit is the derived destination KEY, and that is what preserves merging (SPEC-188)"
description: "The destination guard heads each derived destination KEY, never the subtree, which is what keeps merging into an existing folder legal; a 403 counts as occupied in both modes, and `overwrite` must ask about every key where `refuse` may short-circuit."
---

The destination guard asks, per selected item, whether anything is already where that item's objects
would land. **What it compares is each derived destination KEY, never the destination subtree**, and
the difference is a capability rather than a nuance.

~~That is what the browser does today: `moveFolder` and `copyFolder` intersect `sourceKeys.map(destKeyFor)`
against the listed destination.~~ **— superseded by SPEC-198:** that was the browser's rule until
`moveFolder` and `copyFolder` were deleted. A folder operation now meets this guard only on the
plane, where `_collisions` in `file_ops_check_destinations.py` heads each item's derived destination
keys — the same unit, so merging survived the move. So copying `reports/` into `out/` while `out/reports/notes.txt`
already exists — where no source key maps onto that key — is legal today and stays legal. "The
destination subtree holds anything" is a stricter test that reads as tidier and would silently
remove **merging into an existing folder**, which is how people actually use a file browser.

**It heads every key rather than listing the destination, and a listing structurally cannot serve
the check.** `CommonPrefixes` carries no `LastModified`, `Size` or keys, so a delimited listing
cannot answer the overwrite predicate below the first level; and `ListObjectsV2` never returns a
per-key 403 — an `AccessDenied` fails the whole listing. HEADs are also bounded by **our own**
`FILE_OPS_MAX_OBJECTS` rather than by the size of someone else's destination folder.

**A 403 counts as OCCUPIED, in both modes**, inherited from the archive guard for the same reason: a
key this role cannot head is one it must not overwrite, and under `overwrite` it yields no
`LastModified`, so "an existing object" must never be read as "the ones we could head". A head that
faults for any other reason refuses its item; it never falls through to clear.

**`refuse` short-circuits and `overwrite` cannot**, and the asymmetry is stated because a shared
early exit would silently make `overwrite` sample-dependent — a newer object *anywhere* in an item's
key set refuses it, so the whole set has to be asked about. The corollary is that the ordinary case
costs a full sweep either way: a clean item is always `objectCount` heads, which is what the verb's
timeout is sized for.

**The overwrite predicate reads `submittedAt` from the PLAN with no fallback to the state**, and an
unusable instant refuses the request rather than degrading the mode. A fallback would reintroduce
exactly the substitution `plan_superseded` exists to catch, and a silent degrade would apply refuse
semantics — *with* the short-circuit that mode must never take — to a request the user confirmed as
an overwrite.

**The conflict sample is bounded by the STATE, not by taste.** Every conflicted item carries its
sample from the guard to the notification, and Step Functions caps a state at 256 KB. Measured at the
selection byte cap with every item conflicted, one full-length path per item is all that fits — so a
sampled path is shortened from the middle to `FILE_OPS_SAMPLE_PATH_CHARS`, which keeps the basename,
and three of them fit with room over. An ordinary path is untouched.

## History

### 2026-08-17

- **Settled:** SPEC-188.
