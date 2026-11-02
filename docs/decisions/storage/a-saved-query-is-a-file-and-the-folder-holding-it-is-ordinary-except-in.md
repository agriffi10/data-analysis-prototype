---
type: Decision
title: "A saved query is a FILE, and the folder holding it is ordinary except in one respect (SPEC-173)"
description: "**Saved queries are ordinary `.sql` files** in a visible folder with exactly one protection: the folder itself is undeletable. Every `DO_NOT_DELETE.txt` is hidden by **basename**."
---

**Decision (2026-08-11).** Saved queries move out of `{username}/user_settings/saved-queries.json`
and become `.sql` objects in `{root}saved_queries/`, a folder at a space root. The folder is
**visible, browsable, uploadable into, a valid move/copy destination and free to hold subfolders**;
individual files inside it may be deleted by anyone with access to the space. Exactly one thing is
protected: the folder **itself** cannot be deleted or renamed. It appears in
`UNDELETABLE_ROOT_FOLDERS` and in **neither** of the other two lists, and a test asserts that
absence, because `protectedFolders.ts`'s three lists answer three questions (see / paste / destroy)
and this folder is the second case that proves they are not a union. Rename is a move — S3 has
neither — so ~~`moveFolder`'s existing refusal covers both with no new guard.~~ **— superseded by
SPEC-198:** one move refusal still covers both, though `moveFolder` is deleted. A folder move or
rename runs on the file-operations plane, whose `source_refusal` (`focommon/protected.py`) refuses
the folder as a move source; the browser states the refusal first, through
`undeletableRootFolderRefusal(folderPrefix, rootPrefix, 'move')` and `undeletableSelectionRefusal`
for a selection made only of protected folders ([*The folder-recursive functions are deleted, not
ported*](the-folder-recursive-functions-are-deleted-not-ported-and-the-flag.md)).

**What keeps the load list coherent is a FILTER, not a write lock.** Because anyone may drop a CSV
or a folder tree in, the store offers **top-level `.sql` files and nothing else**; that filter is a
requirement with tests rather than a precaution, and `Delimiter: '/'` is load-bearing beside it
(`saved_queries/archive/old.sql` is a file in a folder, not a saved query). The depth check is
asserted in the service too, so one-level-ness is a property of the STORE and not of one request's
parameters. A folder the user cannot treat as a folder is a folder they will fight, and a saved
query nobody can throw away is one that accumulates forever — the narrowness is the design.

**The key is the identity and the filename is the name.** There is no id and no record, because a
`.sql` file cannot carry one without a sidecar this feature deliberately does not have. The listing
returns S3's own (lexicographic) order, unmodified: sorting by last-modified across a paginated
listing is the lie SPEC-123 records about the data-quality runs index — the newest query may sit on
page nine, and a client-side re-sort of the loaded pages makes rows the user has already seen jump
between pages as later pages arrive.

**The queries in the old store are abandoned, not migrated** (user decision). The portal is
pre-production with no real users, and a migration is code with one execution and no way to test
its second run. The document is left in place (`user_settings/` denies delete) and the store's code
is **deleted**, so there is one saved-queries system in the tree and no second definition of what a
saved query is.

**Three user-visible losses, each accepted on its own reasoning.** The drawer loses its **SQL
preview**: a `.sql` object carries no body until it is read, so a preview means a `GetObject` per
row on every open — twenty-five round trips to show twenty-five one-line snippets. **Every Save now
asks for a name**, a linked tab's included, pre-filled and selected, where SPEC-043 wrote back
silently: a user about to overwrite a file should be told which file, in which space. And the
collision check moves from a case-insensitive scan of the loaded array to a **HEAD on the exact
key** inside `writeSavedQuery` — the scan stopped being sound once the list is paginated and the
target space may not be the one on screen — so `Report` and `report` are now two saved queries,
because S3 keys are case-sensitive.

**The dirty marker is a SESSION SNAPSHOT, and its gap is stated rather than discovered.** SPEC-043
compared a tab's buffer with the `sql` field on a store row; there is no such field. The workspace
keeps a `key → sql` map of what this session last saw — the body fetched when a query was opened,
or the buffer just written by a save — and marks a tab dirty against that. A tab restored from
`sessionStorage` after a reload therefore shows no marker until it is opened or saved again. The
alternative was a `GetObject` per linked tab on every mount, which is the same trade the preview
line lost.

**Do NOT build:** a sidecar metadata file beside each `.sql`; a recursive listing (a `.sql` file
the user tucks into a subfolder is a normal file, reachable from the file browser and not from the
editor); a write lock or an allowed-extensions guard on the folder's contents; a migration from the
JSON store; or an autosave of any kind — FR-010 is a tripwire test with a zero-`PutObject` count,
because the failure it guards is silent and lands in someone else's shared space.

## History

### 2026-08-11

- **Settled:** SPEC-173.
