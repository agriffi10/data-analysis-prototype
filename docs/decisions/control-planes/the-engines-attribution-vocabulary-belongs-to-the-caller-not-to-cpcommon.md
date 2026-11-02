---
type: Decision
title: "The engine's attribution vocabulary belongs to the CALLER, not to cpcommon (SPEC-189)"
description: "`cpcommon.transfer` takes a caller-supplied `echo_fields` with no default, in both its failure-record builders, so attribution vocabulary belongs to the caller; an echoed field stays bounded, so echo a name and never a key set."
---

`cpcommon.transfer.copy_batch` and `results._from_input` built their failure records as
`{recipient, kind, reason}`, hardcoded to table-share's vocabulary. This plane attributes to a
**selected item**, and there was no field to carry it: an `itemKey` on a manifest line rode into the
child input and was dropped on the way out. The engine now takes a caller-supplied `echo_fields` set
in **both** halves — they are separately implemented, one copying what the batch verb wrote and one
rebuilding it, which is exactly the pair that drifts, and a drifted record is one the caller
silently cannot attribute.

**`echo_fields` has no default.** A default hands a new caller either table-share's vocabulary or an
empty set, and both are wrong without a review. Table-share and file-send pass
`("recipient", "kind")` and their records are byte-identical, measured by rendering both rather than
argued. **Archive passes the empty set and its records change**: its manifest carries neither field,
so every archive failure used to read `{"recipient": null, "kind": null, …}`. A named test says the
two nulls are gone on purpose. **— superseded in part 2026-09-21: archive now echoes one field,
the boolean `folder`, so a sentence about a shortfall can count files ([the archive register's
entry](../archive-and-restore/a-folder-placeholder-is-not-a-file-to-the-person-reading-the-count.md));
the two nulls stay gone —**

**The echoed fields must stay bounded.** The list rides the exported result and then the state, where
a key list is the unbounded term that breaches the 256 KB limit **on the Map** — destroying every
per-item outcome the export exists to preserve. Echo a name, never a key set.

## History

### 2026-09-21

- **Changed:** Archive now echoes one field, the boolean `folder`, so a sentence about a shortfall can count files; the two nulls stay gone.

### 2026-08-17

- **Settled:** SPEC-189.
