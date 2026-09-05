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
move is **two merges** with live checks between them, the shape SPEC-202 settled for a cutover:
first the writes switch and the existing objects follow, while the old paths are still fully
protected so every step can be reversed; then, once the checks pass, the old-path statements and
rules come out and the old prefixes are proved empty positively. After the second merge there is
no rollback, and the spec says so.

## Scope

### In Scope

- The write switch: `app_managed_prefix` / `appManagedPrefix` resolve to
  `{root}system_settings/{folder}/`, and everything built on them follows — Athena output locations,
  new shared tables' `LOCATION`, receipt folders, results folders.
- A one-shot, CI-run migration that copies every existing object under the three folders to its
  new home, re-points every shared table's Glue `LOCATION`, and deletes a source only once its copy
  is confirmed.
- The browser: the group row deleted, `system_settings/` an ordinary-looking folder row with the
  protections SPEC-219 gave it, the three folders inside with their rules at depth two.
- Live checks between the merges, against the four traps the arc names.
- The narrowing: old-path IAM statements out, the plural builders shrunk to their one remaining
  element, the old prefixes proved empty, the Checkov accept list re-measured.

### Out of Scope

- **The Glacier vault's layout.** `VAULT_ARCHIVE_SEGMENT` and every key in the archive bucket stay
  where they are; the FIFO golden vectors pass untouched. Only the user's receipt folder moves.
- **The admin bucket's `archive/*` scratch prefix** (`arcommon.plan.PREFIX`) and its lifecycle rule.
- **`user_settings/`, `saved_queries/`, `_data-quality-reports/`** and every other non-moving
  folder; they are neither moved nor swept.
- **Renaming the three folders**, or changing what a user may do inside them. `athenaresults/` stays
  visible, browsable and undeletable; `archive/` stays read-only; `shared_tables/` stays a folder
  the share pipeline fills.
- **Any change to the group-row's caption or behaviour**: it is deleted, not restyled.
- **A migration that overwrites.** A destination key that already exists with different content is
  reported and left alone, never replaced.

---

## Functional Requirements

### FR-001: The writes switch, and everything built on the builder follows

#### Description:

`app_managed_prefix(root, folder)` returns `f"{root}{SYSTEM_SETTINGS_FOLDER}/{folder}/"` and
`appManagedPrefix` its twin. Because SPEC-218 routed every construction through them, the Athena
output location (`cpcommon.results`, `api/routes/athena.py`), a new shared table's `destPrefix` and
`LOCATION` (`table_share_check_target_absent`, `table_share_create_table`), the receipt folder
(`arcommon.paths.receipt_root`) and the file-send/file-ops excluders all move with one edit per tree.
`app_managed_prefixes` still returns both, old first, so the old objects stay protected until FR-005.

#### Acceptance Criteria:

- [ ] `app_managed_prefix("alice/", "archive") == "alice/system_settings/archive/"` and
      `appManagedPrefix('alice/', 'archive') === 'alice/system_settings/archive/'`; the SPEC-218
      builder tests are rewritten to the new values and to nothing else.
- [ ] `results_location("b", "alice", "bob") == "s3://b/alice/system_settings/athenaresults/bob/"`;
      the API's Athena start route submits that output location for the verified claim; the
      table-share destination is `{name}/system_settings/shared_tables/{table}/`; a receipt root is
      `{name}/system_settings/archive/{uuid}/` — each asserted where SPEC-218 asserted the old value.
- [ ] `vault_archive_prefix` is untouched and `test_fifo_derivations.py`'s golden vectors pass
      unchanged — the check that fact 2 did not move.
- [ ] `app_managed_prefixes` still lists the depth-one location, and every parametrised old/new pair
      test from SPEC-219 still passes.
- [ ] The sweep is clean and its corpus passes; the population test is untouched by this FR (the
      templates do not change until FR-005).
- [ ] The switch is one PR, containing no migration and no narrowing, so that reverting it puts
      every new write back at depth one with nothing else to undo.

### FR-002: The existing objects follow, and no source is deleted before its copy is confirmed

#### Description:

A `workflow_dispatch` workflow — its own file, on the `backfill-ever-active.yml` precedent, run from
`main` under the deploy role, since a production write from a session is not available — drives a
Python module that, for every space in both buckets, copies `{space}/{folder}/**` to
`{space}/system_settings/{folder}/**` for the three folders, then re-points the Glue `LOCATION` of
every table whose location sits under an old `shared_tables/` path, then deletes the confirmed source
keys. Three modes, as the precedent has: `report` prints the plan and writes nothing; `copy` copies
and re-points but deletes nothing; `finish` deletes the sources whose copies it re-verifies. The
verification is per key: the destination exists and its `ETag` equals the source's (single-part) or
its size and last-modified-after the copy agree (multipart); a destination that exists with
different content is **reported and skipped**, never overwritten, and its source is never deleted.

#### Acceptance Criteria:

- [ ] `report` lists, per bucket and space, the number of keys and bytes under each old prefix, the
      number already present at the new prefix, and every Glue table whose `LOCATION` would change,
      and writes nothing — asserted against a moto- or fake-backed bucket in the module's tests.
- [ ] `copy` is idempotent: a second run copies zero keys, re-points zero tables and reports the
      same counts; a destination key that already exists with a different `ETag` is listed under
      `conflicts`, not copied, and the run exits non-zero so the operator reads the list.
- [ ] `finish` deletes only keys whose destination it has just re-verified, in batches of at most
      1000 with the per-item `Errors` array read (a partial failure is not a success), and refuses
      to run while `conflicts` is non-empty.
- [ ] Storage class, content type, user metadata and the `x-amz-tagging` set survive the copy;
      receipts keep their folder name, which is the archive id, so a pasted id still resolves.
- [ ] Every Glue table under an old `shared_tables/` location is re-pointed with `update_table` (the
      refresh verb's read-modify-write, `SkipArchive=True`), and `SELECT count(*)` against one such
      table returns the same count before and after — the arc's zero-rows trap, asserted live.
- [ ] The module carries no inline comments, every function a docstring, and joins `mypy`'s file
      list entering at zero; the workflow refuses a dispatch from any ref but `main`.
- [ ] The order is fixed and recorded in the delivery doc: FR-001 merged and deployed, then `report`,
      `copy`, the FR-004 checks, `finish` — so no object is ever written to the old prefix after the
      copy began.

### FR-003: The browser shows the real folder and drops the row that imitated it

#### Description:

`SystemFolderGroupRow`, `partitionSystemFolders`, `SYSTEM_GROUPED_FOLDERS` and
`systemFolderGroupCaption` are deleted. `system_settings/` is listed as a folder row like any other,
sorted among the user's folders, with the refusals SPEC-219 gave it; opening it lists the three
folders, each with the rules it had at the root now at depth two. The reservation of the name
`system_settings` in `validateFolderName` stays — a user must not be able to create a folder that
would sit beside the real one in a different case or collide with it. Help text is re-read: the
sentence that says the folders are "gathered under `system_settings`" is now literally true, and any
sentence describing the row's disclosure behaviour is removed.

#### Acceptance Criteria:

- [ ] No module under `apps/portal/src` imports `SystemFolderGroupRow` or `partitionSystemFolders`;
      the two files and their tests are deleted, and `SYSTEM_GROUPED_FOLDERS` is gone from the
      inventory. A rename-vacated negative query is not enough: the assertion is on the module graph.
- [ ] At a space root, the listing shows `system_settings/` as one folder row with no disclosure
      control and no caption; selecting it disables Delete, Move and Archive each with its reason;
      the destination picker does not offer it; New folder refuses the name.
- [ ] Inside `system_settings/`, `athenaresults/` is undeletable with the results reason, `archive/`
      is read-only throughout (upload, new folder, rename, move, delete removed with the write-lock
      reason), and `shared_tables/` is not a paste target — the same three rows the e2e guide has for
      them at the root today, re-keyed to the new location.
- [ ] Help & guides: the archive entry's "under `system_settings` → `archive`" is unchanged; the file
      browser entry no longer describes a collapsed row; the restore dialog's wording is unchanged.
- [ ] `docs/testing/e2e.md`'s file-browser table drops the `system_settings` row-behaviour row and
      re-keys the three folder rows; the archive section's "open `system_settings` first" step is
      re-read against the real folder.

### FR-004: Live checks between the merges, while the rollback still works

#### Description:

With FR-001 deployed and FR-002 run through `copy`, and the old statements and rules still in place,
the four traps the arc names are exercised against the account. Only after every row is discharged
does `finish` run and FR-005 land.

#### Acceptance Criteria:

- [ ] **Glue `LOCATION`.** A shared table whose data moved returns the same row count as before the
      migration; a table shared AFTER the switch has a `LOCATION` under `system_settings/shared_tables/`
      and returns rows.
- [ ] **Archive ids.** An archive made after the switch leaves its receipt under
      `system_settings/archive/{uuid}/`; a restore by that id succeeds; a restore by an id whose
      receipt was migrated succeeds; the notification link lands in the new folder.
- [ ] **First-segment rules.** A data-quality check targeting `system_settings/athenaresults/x` is
      refused as a reserved prefix, and one targeting a user's ordinary folder still runs.
- [ ] **FIFO group ids.** The vectors are unit-asserted (FR-001); live, two restores of one archive
      id submitted together collapse to one execution, as before.
- [ ] Query results land under `system_settings/athenaresults/` and appear in the browser there;
      *Save results to my files* still reads the CSV.
- [ ] A `PUT` under both `{root}archive/` and `{root}system_settings/archive/` is still refused at the
      route layer, and a `put-object` with the portal role to either is `AccessDenied` — the proof
      that the rollback (revert FR-001, re-run `copy` in reverse is NOT offered; the objects are
      simply still readable at both homes) leaves nothing unprotected.
- [ ] Each check is a row in `docs/testing/e2e.md` (browser) or `docs/testing/owed.md` (CLI), marked
      discharged with the date and the request id where one exists.

### FR-005: The narrowing, and the old prefixes proved empty

#### Description:

The second merge. Every old-anchor sibling comes out of the eight templates; the population test's
expected pairs shrink to the `system_settings/` anchors; `app_managed_prefixes` /
`appManagedPrefixes` shrink to a one-element tuple — an edit inside the two owner modules and
nowhere else, which is why SPEC-219 typed them `tuple[str, ...]` — so every rule that consults
them now protects the new home alone; the lists keep `system_settings` (`RESERVED_PREFIXES` too,
since every moving folder is now a child of it). The old prefixes are proved empty **positively**: `list-objects-v2 --max-keys 1` under
`{space}/{folder}/` for every space in both buckets returns no `Contents`, read from the account, not
from a plan. The Checkov plan-scan accept list is re-measured, because a removed statement whose
findings were accepted makes the acceptances stale, which is a hard error (SPEC-202).

#### Acceptance Criteria:

- [ ] The population test's expected table has exactly one pair per file per folder, all anchored
      `system_settings`, and the two admin-bucket entries unchanged; it fails if any old-anchor
      Resource survives (plant one, watch it name the file, revert).
- [ ] `app_managed_prefixes(root, f)` returns exactly `(app_managed_prefix(root, f),)` and
      `appManagedPrefixes` its twin; no rule module changes in this merge (asserted by the diff:
      only the two owner modules, the templates, the tests and the docs); every SPEC-219
      parametrised pair test is rewritten to the single location, and the archive/file-send/
      file-ops refusal tests for a depth-one `alice/archive/x` now expect the key to be treated as
      an **ordinary** user path.
- [ ] `checkov` on the deploy plan: zero unaccepted findings and zero stale acceptances; the accept
      list's diff, if any, is in the PR with a one-line disposition per line.
- [ ] Proved empty, recorded in `docs/testing/owed.md` with the command and the date: for every
      top-level prefix in the user-space bucket and every space in the shared-space bucket,
      `aws s3api list-objects-v2 --bucket … --prefix {space}/athenaresults/ --max-keys 1` (and
      `archive/`, `shared_tables/`) returns no `Contents`. A space that still holds a key blocks the
      merge.
- [ ] The delivery doc states plainly that after this merge there is no rollback — the old-path
      statements are gone and the objects are gone — and names the merge commit of FR-001 as the
      last point at which reverting was a plan.
- [ ] `ARCS.md`'s arc entry gains its in-place note that the row from #641 is deleted and the prefix
      is real; `docs/testing/e2e.md` and `owed.md` carry no path keyed on a root-level
      `athenaresults/`, `archive/` or `shared_tables/`.

---

## Data Model

```py
# lambdas/system-settings-migrate/system_settings_migrate.py  (new function directory; joins fleet.py
# by Terraform, on the deploy-lambdas rule that every function is pointed every run)

Mode = Literal["report", "copy", "finish"]

class Plan(TypedDict):
    bucket: str
    space: str
    folder: str            # one of the three
    keys: int
    bytes: int
    already_present: int
    conflicts: list[str]   # destination keys that exist with different content
    tables: list[str]      # Glue tables whose LOCATION moves, "database.table"
```

## File & Folder Structure

```
.github/workflows/migrate-system-settings.yml     # workflow_dispatch: report | copy | finish
lambdas/system-settings-migrate/
├── system_settings_migrate.py                    # the module; invoked by the workflow
└── test_system_settings_migrate.py
infra/modules/data/…                              # the function, its role: copy/list/delete on both
                                                  #   space buckets under the three prefixes only,
                                                  #   glue:GetTables/UpdateTable — measured with
                                                  #   simulate-custom-policy, grants in their own PR
apps/portal/src/features/file-browser/            # SystemFolderGroupRow.tsx, systemFolders.ts and
                                                  #   their tests DELETED; FileListTable/FileBrowser
                                                  #   lose the partition
apps/portal/src/features/help/helpContent.ts      # the file-browser entry re-read
docs/testing/e2e.md · docs/testing/owed.md        # re-keyed rows; the proved-empty row
```

## Implementation Phases

### Phase 1: The migration function and its grants (grants first, own PR)

- The function directory, its module and tests against a fake bucket; the execution role scoped to
  the three prefixes in both buckets and to Glue `GetTables`/`UpdateTable`, measured with
  `simulate-custom-policy`; the `workflow_dispatch` workflow refusing non-`main` refs.

### Phase 2: The switch (merge one)

- The two singular builders flipped; the SPEC-218 value tests rewritten; the browser row deleted
  and the listing re-checked; Help and the e2e rows re-keyed. One PR.

### Phase 3: `report`, `copy`, and the live checks

- Run from `main`; discharge every FR-004 row; then `finish`.

### Phase 4: The narrowing (merge two)

- Old-anchor Resources out; the population test to single anchors; the plural builders shrunk to
  one element and every pair test rewritten; the accept list re-measured; the proved-empty row; the
  delivery doc's no-rollback sentence and the arc note.
