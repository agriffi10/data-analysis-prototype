---
type: Decision
title: "The folder names ARE the archive ids, so the folder must stay visible"
description: "An archive's id is its receipt folder's name, so that folder stays visible one click in under `system_settings` and undestroyable, and all user-facing prose must name that path."
---

An archive is identified by a UUID the browser minted, and the user needs it back to restore. There
are three places it could come from: a notification, the receipt, and the folder that holds the
receipt. The notification is transient and the receipt is inside the folder — so the FOLDER is the
durable surface, and `archive/` is therefore the first app-managed root that is visible, unpasteable
and undestroyable at once.

**Amended: visible now means one click in, not top of the listing.** `archive/` sits inside the
`system_settings` group row with the other two folders the app fills — a collapse, not a hide, and
the distinction is the whole of what keeps this decision intact: the folder names are still the
durable surface and `ls` is still the index. What the grouping DID falsify was the prose, which sent
users to "your archive folder" at a root where it no longer appears; the restore dialog and both
help entries now name the `system_settings` → `archive` path, and they are load-bearing rather than
descriptive. A future change that collapses this row without carrying that wording is the failure
this paragraph exists to prevent — the id is needed at exactly the moment the user has nothing else
to go on.

That is also why this spec ships **no archive index, no archive browser and no picker of past
archives**. A cross-space index is the directory-shaped disclosure SPEC-158 declined; a per-space
one would be a second, weaker copy of a listing the file browser already renders. `ls` is the index.

**The receipt is downloaded and read, not previewed.** The project's no-in-browser-preview rule is
untouched, and this is the intended surface rather than a workaround: the ids are readable from the
folder names without opening anything at all.

## History

### 2026-08-12

- **Settled:** entered the register.
