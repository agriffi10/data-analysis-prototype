# Spec: Move the App-Managed Folders, Then Narrow

**ID:** SPEC-220
**Status:** Draft
**Last Updated:** 2026-09-05
**Depends On:** SPEC-219

## Overview

With both homes fenced (SPEC-219), the three app-managed folders can actually move. After this
spec a space's root holds the user's own folders and one real `system_settings/` folder; inside it
sit `athenaresults/`, `archive/` and `shared_tables/`, exactly what the disclosure row has been
standing in for since #641 — and that row is deleted, because the thing it imitated now exists. The
move is **two merges with a migration between them**, the shape SPEC-202 settled for a cutover:
first the writes switch, while both homes stay fully protected; then a CI-run migration copies the
existing objects across and, once every live check passes, deletes the sources; then the old-path
statements and rules come out and the old prefixes are proved empty positively. There are **two
points of no return**, and the spec names both: the migration's `finish` run for the objects, and
the second merge for the fences.

## Scope

### In Scope

- The write switch: `app_managed_prefix` / `appManagedPrefix` resolve to
  `{root}system_settings/{folder}/`, and everything built on them follows — Athena output locations,
  new shared tables' `LOCATION`, receipt folders, results folders. The plural builders are untouched,
  so both homes stay protected.
- A one-shot migration, a module under `scripts/` run by a `workflow_dispatch` workflow under the
  deploy role, that copies every existing object under the three folders to its new home, re-points
  every shared table's Glue `LOCATION`, and deletes a source only against a recorded confirmation.
- The browser: the group row deleted, `system_settings/` an ordinary-looking folder row with the
  protections SPEC-219 gave it, the three folders inside with their rules at depth two.
- Live checks between the switch and `finish`, against the four traps the arc names.
- The narrowing: old-anchor IAM statements and elements out, the plural builders shrunk to their one
  remaining element, the old prefixes proved empty, the Checkov accept list re-measured.

### Out of Scope

- **The Glacier vault's layout.** `VAULT_ARCHIVE_SEGMENT` and every key in the archive bucket stay
  where they are; the FIFO golden vectors pass untouched. Only the user's receipt folder moves.
- **The admin bucket's `archive/*` scratch prefix** (`arcommon.plan.PREFIX`) and its lifecycle rule.
- **`user_settings/`, `saved_queries/`, `_data-quality-reports/`** and every other non-moving
  folder; they are neither moved nor swept.
- **Renaming the three folders**, or changing what a user may do inside them. `athenaresults/` stays
  visible, browsable and undeletable; `archive/` stays read-only; `shared_tables/` stays a folder
  the share pipeline fills.
- **Any change to the group row's caption or behaviour**: it is deleted, not restyled.
- **A migration that overwrites, or that resolves a conflict on its own.** A destination key that
  already exists with different content is reported and left alone; an operator resolves it by hand
  (FR-002) and the migration re-runs to zero.
- **A new Lambda function.** The migration is a runner script under the deploy role, which already
  holds `s3:*` on both space buckets, Glue catalog management, Lake Formation admin and a place in
  the user-space bucket-policy allowlist; a fleet function would need a new role that the allowlist
  does not name, and its first `CopyObject` would be `AccessDenied` behind a green apply.

---

## Functional Requirements

### FR-001: The writes switch, and everything built on the singular builder follows

#### Description:

`app_managed_prefix(root, folder)` returns `f"{root}{SYSTEM_SETTINGS_FOLDER}/{folder}/"` and
`appManagedPrefix` its twin. Because SPEC-218 routed every construction through them, the Athena
output location (`cpcommon.results`, `api/routes/athena.py`), a new shared table's `destPrefix` and
`LOCATION` (`table_share_check_target_absent`, `table_share_create_table`), the receipt folder
(`arcommon.paths.receipt_root`) and the file-send/file-ops excluders all move with one edit per
tree. The plural builders spell both homes as **literals** (SPEC-219 FR-002/FR-003), so they are
untouched by this switch and every rule that consults them — `_IGNORED_SUBTREES` included, which
SPEC-219 built from the plural — keeps protecting the old home while its objects are still there;
SPEC-219's today-equality assertions that the plural's first element equals the singular are
**deleted** here, since the two now legitimately differ.

#### Acceptance Criteria:

- [ ] `app_managed_prefix("alice/", "archive") == "alice/system_settings/archive/"` and
      `appManagedPrefix('alice/', 'archive') === 'alice/system_settings/archive/'`; the SPEC-218
      builder tests are rewritten to the new values and to nothing else.
- [ ] `app_managed_prefixes("alice/", "archive") == ("alice/archive/", "alice/system_settings/archive/")`
      still — asserted against the literal strings, not against the singular — and every SPEC-219
      parametrised old/new pair test passes unchanged, including the old-home rows.
- [ ] `results_location("b", "alice", "bob") == "s3://b/alice/system_settings/athenaresults/bob/"`;
      the API's Athena start route submits that output location for the verified claim; the
      table-share destination is `{name}/system_settings/shared_tables/{table}/`; a receipt root is
      `{name}/system_settings/archive/{uuid}/` — each asserted where SPEC-218 asserted the old value.
- [ ] `vault_archive_prefix` is untouched and `test_fifo_derivations.py`'s golden vectors pass
      unchanged — the check that fact 2 did not move.
- [ ] The sweep is clean and its corpus passes; the population test is untouched by this FR (the
      templates do not change until FR-005).
- [ ] The switch is one PR, containing no migration and no narrowing, so that reverting it puts
      every new write back at depth one with nothing else to undo. Reverting is a rollback only
      until the migration's `finish` run (FR-002); the delivery doc names the merge commit.

### FR-002: The existing objects follow, and a source is deleted only against a recorded confirmation

#### Description:

`scripts/migrate_system_settings.py`, run by a `workflow_dispatch` workflow of its own (on
`backfill-ever-active.yml`'s precedent for a one-shot: manual, `main` only, a `mode` input, a
concurrency group) under the deploy role. It enumerates every space by listing each bucket root with
`--delimiter /` (never from the registry, which cannot know a deleted space's leftover keys), and for
each space and each of the three folders copies `{space}/{folder}/**` to
`{space}/system_settings/{folder}/**`, re-points the Glue `LOCATION` of every table under an old
`shared_tables/` path, and — only in `finish` — deletes the sources. Because IAM no longer bounds it
(the deploy role holds `s3:*`), the module **itself** refuses to read, copy or delete any key outside
`{space}/{folder}/` for the three folders, and to touch any `LOCATION` not under an old
`shared_tables/` path, and a test proves both refusals.

Three modes. `report` prints the plan and writes nothing. `copy` first checks two **preconditions**
— no archive-plane execution is `RUNNING`, and no Athena execution in the workgroup is
non-terminal — because a restore computes its receipt key at validate time and rewrites it hours
later, and a query started before the switch lands its CSV at the old output location minutes
later; either would write to the old prefix after the copy began. Then it copies, recording per key
the source's `ETag` and `LastModified` and the `CopyObjectResult.ETag` the copy returned, and
re-points the tables with `SkipArchive=False` (the refresh verb's choice: the retained version is the
rollback). `finish` re-`HeadObject`s both sides of every recorded key, refuses one whose source no
longer matches its record or whose destination no longer matches what the copy returned, and deletes
with the recorded source `ETag` on the delete's `ObjectIdentifier`, so the guard holds at the delete
rather than at the head.

A destination that already exists with different content is a **conflict**: listed, never
overwritten, its source never deleted, and the run exits non-zero. An operator resolves each by hand
under the deploy role from CI (inspect both objects, keep one, record the decision in the delivery
doc), and re-runs `report` until it shows zero conflicts. A key over 5 GB cannot be copied in one
`CopyObject`; it is listed under `oversize` and refused, to be moved by hand the same way.

#### Acceptance Criteria:

- [ ] `report` lists, per bucket and space, the number of keys and bytes under each old prefix, the
      number already present at the new prefix, every Glue table whose `LOCATION` would change,
      `conflicts` and `oversize`, and writes nothing — asserted against this repo's fake S3 and Glue
      clients (no new test dependency).
- [ ] The module refuses a key outside the three prefixes and a `LOCATION` outside an old
      `shared_tables/` path with a named reason, and a test plants each and asserts the reason.
- [ ] `copy` refuses to start while an archive execution is `RUNNING` or an Athena execution is
      non-terminal, naming the blocker; it is idempotent (a second run copies zero keys, re-points
      zero tables, reports the same counts); storage class, content type, user metadata and the
      `x-amz-tagging` set survive the copy; a receipt keeps its folder name, which is the archive id.
- [ ] `finish` refuses to run while `conflicts` or `oversize` is non-empty; deletes only keys whose
      source and destination both re-verify against the record; sends the recorded source `ETag` on
      each `ObjectIdentifier`; batches at most 1000 and reads the per-item `Errors` array (a partial
      failure is not a success); and a test plants a source rewritten after the copy and asserts it
      is refused, not deleted.
- [ ] Every Glue table under an old `shared_tables/` location is re-pointed with
      `update_table(..., SkipArchive=False)`, and `SELECT count(*)` against one such table returns the
      same count before and after — the arc's zero-rows trap, asserted live.
- [ ] The module joins `mypy`'s file list entering at zero, carries no inline comments and a
      docstring per function; the workflow refuses a dispatch from any ref but `main`.
- [ ] The order is fixed and recorded in the delivery doc with the `finish` run's id: FR-001 merged
      and deployed, `report`, `copy`, the FR-004 checks, `finish`, then FR-005. The `finish` run is the
      point of no return for the objects.

### FR-003: The browser shows the real folder and drops the row that imitated it

#### Description:

`SystemFolderGroupRow`, `partitionSystemFolders`, `SYSTEM_GROUPED_FOLDERS` and
`systemFolderGroupCaption` are deleted, from `FileListTable.tsx`, `FileListMobile.tsx` and
`FileBrowser.tsx` alike, and `systemFolders.ts` with them. `system_settings/` is listed as a folder
row like any other, sorted among the user's folders, with the refusals SPEC-219 gave it; opening it
lists the three folders, each with the rules it had at the root now at depth two. The reservation of
the name in `validateFolderName` stays and now imports `SYSTEM_SETTINGS_FOLDER` from
`lib/appManagedPaths`, with its docstring and its message rewritten to say the folder is the app's,
not that the list uses the name, and its reservation test moved out of the deleted
`systemFolders.test.ts` into `fileBrowser.service`'s tests; the three retired root names (`athenaresults`, `archive`,
`shared_tables`) join that reservation too, so no user folder can ever sit where a home used to be.
`protectedFolders.ts`'s divergence note, which calls the grouping "a fifth question", loses that
paragraph.

#### Acceptance Criteria:

- [ ] No module under `apps/portal/src` imports from `./systemFolders` or `SystemFolderGroupRow`; the
      two modules and their tests are deleted; the inventory rows for them are removed — asserted on
      the module graph (`grep -rn` returns nothing), not by a negative query on a rendered name.
- [ ] At a space root, the listing shows `system_settings/` as one folder row with no disclosure
      control and no caption; selecting it disables Delete, Move and Archive each with its reason;
      the destination picker does not offer it; New folder refuses `system_settings` and each of the
      three retired names with a reason naming the app.
- [ ] Inside `system_settings/`, `athenaresults/` is undeletable with the results reason, `archive/`
      is read-only throughout (upload, new folder, rename, move, delete removed with the write-lock
      reason), and `shared_tables/` is not a paste target — the same rows the e2e guide has for them
      at the root today, re-keyed to the new location in `docs/testing/e2e.md`, whose
      `system_settings` row-behaviour row is deleted.
- [ ] Help & guides: the file-browser and archive entries are unchanged, now literally true (the
      folders are "gathered under `system_settings`"); the restore dialog's wording is unchanged —
      asserted by an empty diff on `helpContent.ts` and `RestoreArchiveDialog.tsx`.

### FR-004: Live checks between the switch and `finish`, while every step is still reversible

#### Description:

With FR-001 deployed and `copy` run, both homes hold the objects and both are fenced. The four traps
the arc names are exercised against the account; only after every row is discharged does `finish`
run. The CLI rows run as a workflow step under the deploy role (no laptop identity holds the portal
role); the IAM rows use `simulate-principal-policy` exactly as SPEC-219 FR-004 does.

#### Acceptance Criteria:

- [ ] **Glue `LOCATION`.** A shared table whose data moved returns the same `count(*)` as before the
      migration; a table shared AFTER the switch has a `LOCATION` under `system_settings/shared_tables/`
      and returns rows.
- [ ] **Archive ids.** One archive made after the switch leaves its receipt under
      `system_settings/archive/{uuid}/`; a restore by that id, submitted **twice** in quick
      succession, runs once (the FIFO group id collapsed the pair) and its completion rewrites
      `receipt.txt` at the **new** key with `Restored to` filled; the notification link lands in the
      new folder. One restore, one bill; the migrated receipts are not restored (each would be
      another 3–5 billed hours), and that is accepted.
- [ ] **First-segment rules.** A data-quality check targeting `system_settings/athenaresults/x` is
      refused as a reserved prefix, and one targeting a user's ordinary folder still runs. This
      re-reads SPEC-219's list and cannot fail once that landed; it is kept as the regression row.
- [ ] Query results land under `system_settings/athenaresults/` and appear in the browser there;
      *Save results to my files* still reads the CSV.
- [ ] A `PUT /v1/objects/content` under both `{root}archive/` and `{root}system_settings/archive/` is
      refused at the route layer from a signed-in session, and `simulate-principal-policy` for the
      portal role returns `explicitDeny` on `PutObject` to both — the proof that reverting FR-001 at
      this point leaves nothing unprotected.
- [ ] Each check is a row in `docs/testing/e2e.md` (browser) or `docs/testing/owed.md` (CLI, run from
      CI), marked discharged with the date and the request id where one exists.

### FR-005: The narrowing, and the old prefixes proved empty

#### Description:

The second merge. Every **old-anchor** statement (three portal-role templates) and array element
(five plane templates) comes out; the `…SystemSettings` Sids keep their names, because
`archiveWriteLock.test.ts` keys on them, and its matcher returns to one Sid per bucket; SPEC-219's
sibling-pair test is deleted, since with no old-anchor statement left it can pass on nothing. The
population test's expected pairs shrink to the `system_settings/` anchors. `app_managed_prefixes` /
`appManagedPrefixes` shrink to a one-element tuple for a member of `MOVING_FOLDERS` — an edit inside
the two owner modules and nowhere else, which is why SPEC-219 typed them `tuple[str, ...]` — so
every rule that consults them now protects the new home alone. `RESERVED_PREFIXES` keeps `system_settings` and, deliberately, the three
depth-one names: a user folder created at a retired home's name is refused by the browser (FR-003)
and must not become a data-quality target by the back door either. The old prefixes are proved empty
**positively**, from the account and not from a plan, and the Checkov plan-scan accept list is
re-measured, because a removed statement whose findings were accepted makes the acceptances stale,
which is a hard error (SPEC-202).

#### Acceptance Criteria:

- [ ] The population test's expected table has exactly one pair per file per folder, all anchored
      `system_settings`, and the two admin-bucket entries unchanged; it fails if any old-anchor
      Resource survives (plant one, watch it name the file, revert).
- [ ] `app_managed_prefixes(root, f) == (app_managed_prefix(root, f),)` and `appManagedPrefixes` its
      twin; the diff of this merge touches the two owner modules, the templates, the tests and the
      docs and **no rule module**; every SPEC-219 pair test is rewritten to the single location, and
      the archive/file-send/file-ops refusal tests for a depth-one `alice/archive/x` now expect the
      key to be treated as an **ordinary** user path.
- [ ] `checkov` on the deploy plan: zero unaccepted findings and zero stale acceptances; the accept
      list's diff, if any, is in the PR with a one-line disposition per line.
- [ ] Proved empty, from a workflow step under the deploy role, recorded in `docs/testing/owed.md`
      with the commands, the run id and the date: for every prefix a `--delimiter /` listing of each
      bucket root returns, `list-objects-v2 --prefix {space}/{folder}/ --max-keys 1` for the three
      folders returns no `Contents`. The loop fails closed on a non-zero exit — an empty result from
      a failed call is not an empty prefix — and a space that still holds a key blocks the merge.
- [ ] The delivery doc states the two points of no return plainly: the `finish` run (named by id)
      for the objects, this merge for the fences; and names FR-001's merge commit as the last point
      at which reverting the switch was a rollback rather than a split store.
- [ ] `ARCS.md`'s arc entry gains its in-place note that the row from #641 is deleted and the prefix
      is real; `docs/testing/e2e.md` and `owed.md` carry no path keyed on a root-level
      `athenaresults/`, `archive/` or `shared_tables/`.

---

## Data Model

```py
# scripts/migrate_system_settings.py  (a runner script under the deploy role; joins mypy's files)

Mode = Literal["report", "copy", "finish"]

class Recorded(TypedDict):
    source_etag: str
    source_last_modified: str
    copied_etag: str          # CopyObjectResult.ETag, what finish re-verifies the destination against

class Plan(TypedDict):
    bucket: str
    space: str
    folder: str               # one of the three
    keys: int
    bytes: int
    already_present: int
    conflicts: list[str]      # destination keys that exist with different content
    oversize: list[str]       # source keys over 5 GB, refused
    tables: list[str]         # Glue tables whose LOCATION moves, "database.table"
    recorded: dict[str, Recorded]   # per source key, written by copy, read by finish
```

## File & Folder Structure

```
.github/workflows/migrate-system-settings.yml     # workflow_dispatch: report | copy | finish; main only
scripts/migrate_system_settings.py                # the module; refuses anything outside the three prefixes
scripts/migrate_system_settings_test.py           # against the repo's fake S3/Glue; plants a rewritten source
apps/portal/src/features/file-browser/            # SystemFolderGroupRow.tsx, systemFolders.ts and their
                                                  #   tests DELETED; FileListTable, FileListMobile and
                                                  #   FileBrowser lose the partition; fileBrowser.service
                                                  #   reserves four names via lib/appManagedPaths
docs/testing/e2e.md · docs/testing/owed.md        # re-keyed rows; the proved-empty row
```

## Implementation Phases

### Phase 1: The migration script and its workflow

- The module and its tests against the fakes: the plan, the two refusals, the preconditions, the
  recorded confirmation and the conditional delete, the rewritten-source plant; the
  `workflow_dispatch` workflow refusing non-`main` refs.

### Phase 2: The switch (merge one)

- The two singular builders flipped; the SPEC-218 value tests rewritten; SPEC-219's tripwire
  deleted; the browser row deleted from all three renderers and the four names reserved; Help
  asserted unchanged; the e2e rows re-keyed. One PR.

### Phase 3: `report`, `copy`, the live checks, `finish`

- Run from `main`; resolve any conflict by hand and re-run `report` to zero; discharge every FR-004
  row; then `finish`, and record its run id.

### Phase 4: The narrowing (merge two)

- Old-anchor statements and elements out; the population test to single anchors; the sibling test
  deleted; the plural builders shrunk to one element and every pair test rewritten; the accept list
  re-measured; the proved-empty row; the delivery doc's two points of no return and the arc note.
