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
  `{root}system_settings/{folder}/`, and everything built on the **singular** follows — Athena output
  locations, new shared tables' `LOCATION`, receipt folders, results folders. The plural builders and
  every rule on them are untouched, so both homes stay protected.
- The deploy role's three missing grants, in their own PR before the migration runs.
- A one-shot migration, a module run by a `workflow_dispatch` workflow under the deploy role, with a
  persisted copy record, preconditions on in-flight work, and a `resolve` mode for conflicts. It
  copies every existing object under the three folders to its new home, re-points every shared
  table's Glue `LOCATION`, and deletes a source only against the record.
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
- **Reserving the three retired names.** After the narrowing `alice/athenaresults/` is an ordinary
  user path, at the root as at any depth — `validateFolderName` keeps refusing `system_settings`
  and nothing else. An earlier draft reserved the three names too; it was dropped because the
  validator runs at every depth (it would have refused `alice/projects/archive/`, which SPEC-219 and
  FR-005 call ordinary) and because uploads, plane moves and pastes create folders without it, so it
  could not deliver what it promised. **This is a product-visible decision; the arc entry in
  `ARCS.md` carries it as a dated note from the day these drafts landed, so it is seen before anything
  is irreversible. If the user wants the names reserved at the root, that is a root-aware validator
  and a small spec of its own.**
- **Any change to the group row's caption or behaviour**: it is deleted, not restyled.
- **A migration that overwrites, or that resolves a conflict on its own.** A destination key that
  already exists with different content is reported and left alone; an operator resolves it through
  the workflow's `resolve` mode (FR-002) and the migration re-runs to zero.
- **A new Lambda function.** The migration is a runner script under the deploy role, which already
  holds `s3:*` on both space buckets, is a Lake Formation data-lake admin
  (`analytics/lakeformation.tf`, `admins`), and is named in the user-space bucket-policy allowlist;
  a fleet function would need a new role that the allowlist does not name, and its first
  `CopyObject` would be `AccessDenied` behind a green apply.
- **Saving a pre-switch result after `finish`.** `useSaveResults` copies from the `OutputLocation`
  the execution reported; a result still on screen from before the switch points at a source
  `finish` deleted, and that save fails with the ordinary not-found refusal. Accepted; a re-run of
  the query is the remedy.

---

## Functional Requirements

### FR-001: The writes switch, and everything built on the singular builder follows

#### Description:

`app_managed_prefix(root, folder)` returns `f"{root}{SYSTEM_SETTINGS_FOLDER}/{folder}/"` and
`appManagedPrefix` its twin. Because SPEC-218 routed every construction through them, the Athena
output location (`cpcommon.results`, `api/routes/athena.py`), a new shared table's `destPrefix` and
`LOCATION` (`table_share_check_target_absent`, `table_share_create_table`) and the receipt folder
(`arcommon.paths.receipt_root`) all move with one edit per tree. **Nothing that SPEC-219 routed
through the plural is touched**: the excluders, the refusals and `_IGNORED_SUBTREES` read both homes
from literals, and re-pointing any of them to the singular here would drop protection of the old
home before `finish`. SPEC-219's today-equality assertions that the plural's first element equals
the singular are **deleted** here, since the two now legitimately differ, and the `ACCEPTED_`
tripwire on the three `archive` facts is revisited as its docstring asks: `RECEIPT_FOLDER` is still
spelled `archive` (the folder keeps its name; its parent changed), so the assertion stands and the
docstring records the revisit.

#### Acceptance Criteria:

- [ ] `app_managed_prefix("alice/", "archive") == "alice/system_settings/archive/"` and
      `appManagedPrefix('alice/', 'archive') === 'alice/system_settings/archive/'`; the SPEC-218
      builder tests are rewritten to the new values and to nothing else.
- [ ] `app_managed_prefixes("alice/", "archive") == ("alice/archive/", "alice/system_settings/archive/")`
      still — asserted against the literal strings, not against the singular — and every SPEC-219
      parametrised old/new pair test passes unchanged, including the old-home rows; the diff touches
      no rule module.
- [ ] `results_location("b", "alice", "bob") == "s3://b/alice/system_settings/athenaresults/bob/"`;
      the API's Athena start route submits that output location for the verified claim; the
      table-share destination is `{name}/system_settings/shared_tables/{table}/`; a receipt root is
      `{name}/system_settings/archive/{uuid}/` — each asserted where SPEC-218 asserted the old value.
- [ ] `vault_archive_prefix` is untouched and `lambdas/api/test_fifo_derivations.py`'s golden
      vectors pass unchanged — the check that fact 2 did not move.
- [ ] The sweep is clean and its corpus passes; the population test is untouched by this FR (the
      templates do not change until FR-005).
- [ ] The switch is one PR, containing no migration and no narrowing, so that reverting it puts
      every new write back at depth one with nothing else to undo. Reverting is a rollback only
      until the migration's `finish` run (FR-002); the delivery doc names the merge commit.

### FR-002: The existing objects follow, and a source is deleted only against a persisted record

#### Description:

**The grants first, in their own PR.** The deploy role holds `s3:*` on both space buckets but not
`glue:UpdateTable` (its `GlueCatalogManage` statement is database-level), nor `states:ListExecutions`
on any state machine, nor `athena:ListQueryExecutions` / `athena:BatchGetQueryExecution` on the
workgroup. Each is added to `infra/modules/base/policies/`, scoped to the two space databases' tables,
the archive and table-share state machines, and the one workgroup, measured with
`simulate-custom-policy` and landed before Phase 3, on the register's rule.

**The module.** `scripts/migrate_system_settings.py`, run by `.github/workflows/migrate-system-settings.yml`
(on `backfill-ever-active.yml`'s precedent for a one-shot: manual, a `mode` input, a concurrency
group; unlike the precedent it also carries an explicit step that fails on any ref but `main`). It
imports the four folder names from `cpcommon.app_managed` through the `sys.path` shim
`scripts/generate_api_contract.py` already uses — never as literals — and the sweep's Python tree
gains `scripts/` so a literal there is refused, with the sweep's own module and corpus excluded by
path (they spell `"archive"` as the rule they enforce, and its filename-prefix exclusions do not
cover them). It enumerates every space by listing each bucket
root with `Delimiter="/"`, skipping the user-space bucket's `_config/` and `_directory/` (they hold
no space), and for each space and each of the three folders copies `{space}/{folder}/**` to
`{space}/system_settings/{folder}/**`, re-points the Glue `LOCATION` of every table under an old
`shared_tables/` path, and — only in `finish` — deletes the sources. Because IAM no longer bounds
it, the module **itself** refuses to read, copy or delete any key outside `{space}/{folder}/` for
the three folders, and to touch any `LOCATION` not under an old `shared_tables/` path; a test plants
each and asserts the reason.

**Four modes, and a record that outlives a run.** `report` prints the plan and writes nothing. `copy`
first checks three **preconditions** — no archive-orchestrator execution `RUNNING`, no table-share
execution `RUNNING`, no Athena execution in the workgroup non-terminal (paged through
`ListQueryExecutions`, which lists the last 45 days newest first) — because a restore computes its
receipt key at validate time and rewrites it hours later, a share computes its `destPrefix` at
validate time and writes its data and `LOCATION` later, and a query started before the switch lands
its CSV at the old output location minutes later; any of them would write to the old prefix after
the copy began. If a precondition fails, the operator waits for the execution to end (a restore is
3–5 hours) and re-dispatches. Then it copies, passing the source's `StorageClass` explicitly (a
`CopyObject` lands in `STANDARD` otherwise) and leaving `MetadataDirective` and `TaggingDirective`
at `COPY` (passing `ContentType` would force `REPLACE` and drop user metadata), records per key the
source's `ETag` and `LastModified` and the `CopyObjectResult.ETag` the copy returned, re-points the
tables with `SkipArchive=False` (the refresh verb's choice: the retained version is the rollback),
and **persists the record** to the admin bucket at `migration/system-settings/{run_id}.json`, so
that `finish` — a separate dispatch — can read it: `finish` takes the run id as an input,
re-`HeadObject`s both sides of every recorded key, refuses one whose source no longer matches its
record or whose destination no longer matches what the copy returned, skips and lists under `absent`
a source a user has since deleted (only `shared_tables/` allows that; the object survives at the new
home), and deletes with the recorded source `ETag` on the `ObjectIdentifier`. **The head re-verify is
the proven guard**; the ETag on the identifier is belt on top of it, because `focommon.delete`
records that conditional delete is unverified live on these buckets.

A destination that already exists with different content is a **conflict**: listed, never
overwritten, its source never deleted, and the run exits non-zero. The fourth mode, `resolve`, takes
one source key and `keep=source|destination`: `keep=source` re-copies the source over the
destination and records it; `keep=destination` records the destination as authoritative so `finish`
deletes the source without a match. Each resolution is logged in the record and named in the
delivery doc. A key over 5 GB cannot be copied in one `CopyObject`; it is listed under `oversize` and
refused, and `finish` refuses to run while `conflicts` or `oversize` is non-empty.

#### Acceptance Criteria:

- [ ] The grants PR: `glue:UpdateTable` (and `GetTable`) on the two space databases' tables,
      `states:ListExecutions` on the archive and table-share machines, `athena:ListQueryExecutions`
      and `athena:BatchGetQueryExecution` on the workgroup — each measured `allowed` with
      `simulate-custom-policy` and `implicitDeny` on a neighbour, applied green before Phase 3, with
      the Checkov plan scan re-read.
- [ ] `report` lists, per bucket and space, the number of keys and bytes under each old prefix, the
      number already present at the new prefix, every Glue table whose `LOCATION` would change and
      its current `count(*)`-ready `LOCATION`, `conflicts`, `oversize` and `absent`, and writes
      nothing.
- [ ] The module refuses a key outside the three prefixes and a `LOCATION` outside an old
      `shared_tables/` path with a named reason; the fakes in `lambdas/shared-space-common/fakes.py`
      are extended — `head_object`, `Delimiter`/`CommonPrefixes` on `list_objects_v2`, a
      `CopyObjectResult.ETag` and metadata/tagging/storage-class carry on `copy_object`, `ETag` on a
      delete identifier, `get_table`/`update_table` on the Glue fake — from the S3 contract rather
      than from the module, and the module's tests live under `lambdas/` (pytest's tree) as
      `lambdas/test_migrate_system_settings.py`, importing the script through the same shim.
- [ ] `copy` refuses to start while any precondition fails, naming the execution; it is idempotent (a
      second run copies zero keys, re-points zero tables, reports the same counts); it writes the
      record and prints the run id; a fake-backed test asserts `StorageClass` is passed through and
      the two directives are left at `COPY`. Attribute preservation on real S3 is a live row (FR-004).
- [ ] `finish` refuses without a run id or while `conflicts` or `oversize` is non-empty; deletes
      only keys whose source and destination both re-verify against the record; lists `absent`
      sources without failing; sends the recorded source `ETag` on each identifier; batches at most
      1000 and reads the per-item `Errors` array (a partial failure is not a success); and a test
      plants a source rewritten after the copy and asserts it is refused, not deleted.
- [ ] `resolve` with `keep=source` re-copies and updates the record; with `keep=destination` marks
      the key so `finish` deletes its source; either way the next `report` shows one fewer conflict.
- [ ] Every Glue table under an old `shared_tables/` location is re-pointed with
      `update_table(..., SkipArchive=False)`; the module joins `mypy`'s file list entering at zero
      (a local gate — CI runs no mypy), carries no inline comments and a docstring per function.
- [ ] The order is fixed and recorded in the delivery doc with the `copy` and `finish` run ids:
      grants PR applied; FR-001 merged and deployed; `report` (recording each shared table's
      `count(*)` **before** the re-point); `copy`; the FR-004 checks; `finish`; then FR-005. The
      `finish` run is the point of no return for the objects.

### FR-003: The browser shows the real folder and drops the row that imitated it

#### Description:

`SystemFolderGroupRow`, `partitionSystemFolders`, `SYSTEM_GROUPED_FOLDERS`, `systemFolderGroupCaption`
and `FileBrowser`'s `systemExpanded` state are deleted, from `FileListTable.tsx`, `FileListMobile.tsx`
and `FileBrowser.tsx` alike, with `systemFolders.ts`, `SystemFolderGroupRow.tsx`, their tests, the
group `describe` in `fileBrowser.a11y.test.tsx` and the seven group tests in `FileBrowser.test.tsx`;
the four comment references in `protectedFolders.ts` are rewritten. `system_settings/` is listed as
a folder row like any other, sorted among the user's folders, with the refusals SPEC-219 gave it;
opening it lists the three folders, each with the rules it had at the root now at depth two.
`validateFolderName` keeps refusing `system_settings` at every depth as it does today, importing
`SYSTEM_SETTINGS_FOLDER` from `lib/appManagedPaths`, with its docstring and message rewritten to say
the folder is the app's rather than that the list uses the name, and its reservation test moved from
the deleted `systemFolders.test.ts` into `fileBrowser.service`'s tests. **Between merge one and
`finish`** the root also shows the three old folders as ordinary-looking rows, still refusing every
write and delete through the plural rules — the e2e rows for that window say so.

#### Acceptance Criteria:

- [ ] `tsc -b` and the vitest suite pass with `systemFolders.ts` and `SystemFolderGroupRow.tsx`
      deleted — the mechanical proof that no importer remains; the inventory rows for them are removed.
- [ ] At a space root after `finish`, the listing shows `system_settings/` as one folder row with no
      disclosure control and no caption; selecting it disables Delete, Move and Archive each with its
      reason; the destination picker does not offer it; New folder refuses `system_settings` with a
      reason naming the app.
- [ ] Inside `system_settings/`, `athenaresults/` is undeletable with the results reason, `archive/`
      is read-only throughout (upload, new folder, rename, move, delete removed with the write-lock
      reason), and `shared_tables/` is not a paste target — the same rows the e2e guide has for them
      at the root today, re-keyed to the new location in `docs/testing/e2e.md`, whose
      `system_settings` row-behaviour row is deleted; and a row for the transitional root (both homes
      listed, both refusing) is added and marked as retired after `finish`.
- [ ] `git diff` of `helpContent.ts` and `RestoreArchiveDialog.tsx` is empty in the switch PR, read
      at review: the archive entry's "under `system_settings` → `archive`" and the file-browser entry's
      "gathered under `system_settings`" are now literally true.

### FR-004: Live checks between the switch and `finish`, while every step is still reversible

#### Description:

With FR-001 deployed and `copy` run, both homes hold the objects and both are fenced. The four traps
the arc names are exercised against the account; only after every row is discharged does `finish`
run. The CLI rows run as a workflow step under the deploy role; the IAM rows use
`simulate-principal-policy` from the operator's own CLI identity, as SPEC-219 FR-004 does — the two
identities differ, and the rows say which.

#### Acceptance Criteria:

- [ ] **Glue `LOCATION`.** A shared table whose data moved returns the `count(*)` `report` recorded
      before the re-point; a table shared AFTER the switch has a `LOCATION` under
      `system_settings/shared_tables/` and returns rows.
- [ ] **Archive ids.** One archive made after the switch leaves its receipt under
      `system_settings/archive/{uuid}/`; a restore by that id, submitted twice in quick succession,
      produces **two executions** (the browser mints a request id per submission, so the FIFO
      dedup does not collapse them) but **one `RestoreObject` bill**, the second ending without a
      retrieval because the verb tolerates `RestoreAlreadyInProgress`; its completion rewrites
      `receipt.txt` at the **new** key with `Restored to` filled; the notification link lands in the
      new folder. The migrated receipts are not restored (each would be another 3–5 billed hours),
      and that is accepted.
- [ ] **First-segment rules.** A data-quality check targeting `system_settings/athenaresults/x` is
      refused as a reserved prefix, and one targeting a user's ordinary folder still runs. This
      re-reads SPEC-219's list and cannot fail once that landed; it is kept as the regression row.
- [ ] Query results land under `system_settings/athenaresults/` and appear in the browser there;
      *Save results to my files* still reads the CSV of a post-switch execution.
- [ ] A migrated object at its new home has the source's storage class, content type, user metadata
      and tags (`head-object` and `get-object-tagging` from the workflow step) — the attribute
      preservation the fakes cannot prove.
- [ ] A `PUT /v1/objects/content` under both `{root}archive/` and `{root}system_settings/archive/` is
      refused at the route layer from a signed-in session, and `simulate-principal-policy` for the
      portal role returns `explicitDeny` on `PutObject` to both — the proof that reverting FR-001 at
      this point leaves nothing unprotected.
- [ ] Each check is a row in `docs/testing/e2e.md` (browser) or `docs/testing/owed.md` (CLI, run from
      CI), marked discharged with the date and the request or run id where one exists.

### FR-005: The narrowing, and the old prefixes proved empty

#### Description:

The second merge. Every **old-anchor** statement (three portal-role templates) and array element
(five plane templates) comes out; the `…SystemSettings` Sids keep their names, because
`archiveWriteLock.test.ts` keys on them, and its matcher returns to one Sid per bucket; SPEC-219's
sibling-pair test is deleted, since with no old-anchor statement left it can pass on nothing;
`test_portal_role_preservation.py`'s gained and lost sets are rewritten to the end state. The
population test's expected pairs shrink to the `system_settings/` anchors — and if SPEC-221's plane
has landed its own `athenaresults` template by then, that file is one more row, not a failure.
`app_managed_prefixes` / `appManagedPrefixes` shrink to a one-element tuple for a member of
`MOVING_FOLDERS` — an edit inside the two owner modules and nowhere else, which is why SPEC-219 typed
them `tuple[str, ...]` — so every rule that consults them now protects the new home alone, and a
depth-one `alice/archive/x` is an ordinary user path. `RESERVED_PREFIXES` keeps `system_settings`,
and keeps the two depth-one names it already holds (`athenaresults`, `shared_tables`; it never held
`archive`) — **the one deliberate exception** to "ordinary": a user folder at a retired home's name
is a legal folder but not a data-quality target, so that the plane's own refusal cannot be confused
with a results folder's. The old prefixes are proved empty
**positively**, from the account and not from a plan, and the Checkov plan-scan accept list is
re-measured, because a removed statement whose findings were accepted makes the acceptances stale,
which is a hard error (SPEC-202).

#### Acceptance Criteria:

- [ ] The population test's expected table has exactly one pair per file per folder, all anchored
      `system_settings`, and the two admin-bucket entries unchanged; it fails if any old-anchor
      Resource survives (plant one, watch it name the file, revert).
- [ ] `app_managed_prefixes(root, f) == (app_managed_prefix(root, f),)` for a member and
      `appManagedPrefixes` its twin; the diff of this merge touches the two owner modules, the
      templates, the tests and the docs and **no rule module**; every SPEC-219 pair test is rewritten
      to the single location, and the archive/file-send/file-ops refusal tests for a depth-one
      `alice/archive/x` now expect the key to be treated as an **ordinary** user path; the
      data-quality first-segment refusal for `athenaresults` is asserted as the named exception.
- [ ] `checkov` on the deploy plan: zero unaccepted findings and zero stale acceptances; the accept
      list's diff, if any, is in the PR with a one-line disposition per line.
- [ ] Proved empty, from a workflow step under the deploy role, recorded in `docs/testing/owed.md`
      with the commands, the run id and the date: for every prefix a `Delimiter="/"` listing of each
      bucket root returns (skipping `_config/` and `_directory/`), `list-objects-v2 --prefix
      {space}/{folder}/ --max-keys 1` for the three folders returns no `Contents`. The loop fails
      closed on a non-zero exit — an empty result from a failed call is not an empty prefix — and a
      space that still holds a key blocks the merge.
- [ ] The delivery doc states the two points of no return plainly: the `finish` run (named by id)
      for the objects, this merge for the fences; and names FR-001's merge commit as the last point
      at which reverting the switch was a rollback rather than a split store.
- [ ] `ARCS.md`'s arc entry gains its in-place note that the row from #641 is deleted and the prefix
      is real (the reservation decision is already recorded there from drafting);
      `docs/testing/e2e.md` and `owed.md` carry no path keyed on a root-level `athenaresults/`,
      `archive/` or `shared_tables/` in a **space** bucket — the vault rows
      (`personal/{user}/archive/…`, fact 2) and the admin-bucket row (`archive/{requestId}/`, fact 3)
      are exempt by name and untouched.

---

## Data Model

```py
# scripts/migrate_system_settings.py  (a runner script under the deploy role; joins mypy's files;
# imports ATHENA_RESULTS_FOLDER, RECEIPT_FOLDER, SHARED_TABLES_FOLDER, SYSTEM_SETTINGS_FOLDER from
# cpcommon.app_managed through the sys.path shim generate_api_contract.py uses)

Mode = Literal["report", "copy", "resolve", "finish"]

class Recorded(TypedDict):
    source_etag: str
    source_last_modified: str
    copied_etag: str            # CopyObjectResult.ETag, what finish re-verifies the destination against
    resolution: Literal["", "keep-source", "keep-destination"]

class Record(TypedDict):        # persisted at s3://{admin bucket}/migration/system-settings/{run_id}.json
    run_id: str
    started: str
    keys: dict[str, Recorded]   # per source key
    tables: dict[str, str]      # "database.table" -> the LOCATION it was re-pointed FROM
    conflicts: list[str]
    oversize: list[str]
    absent: list[str]           # filled by finish: sources gone before deletion
```

## File & Folder Structure

```
infra/modules/base/policies/github-actions-deploy*.json.tftpl   # UpdateTable/GetTable, ListExecutions,
                                                                #   ListQueryExecutions/BatchGet — own PR
.github/workflows/migrate-system-settings.yml     # workflow_dispatch: report | copy | resolve | finish;
                                                  #   an explicit main-only step; run_id / key / keep inputs
scripts/migrate_system_settings.py                # the module; refuses anything outside the three prefixes
lambdas/test_migrate_system_settings.py           # against the extended fakes; plants a rewritten source
lambdas/shared-space-common/fakes.py              # the extensions named in FR-002
scripts/validate_app_managed_paths.py             # its Python tree gains scripts/, itself and its corpus excluded
apps/portal/src/features/file-browser/            # systemFolders.ts, SystemFolderGroupRow.tsx and their
                                                  #   tests DELETED; FileListTable, FileListMobile and
                                                  #   FileBrowser lose the partition and systemExpanded;
                                                  #   fileBrowser.service reserves system_settings via
                                                  #   lib/appManagedPaths; a11y and FileBrowser group tests go
docs/testing/e2e.md · docs/testing/owed.md        # re-keyed rows; the transitional row; the proved-empty row
```

## Implementation Phases

### Phase 1: The grants (own PR) and the migration script

- The three deploy-role grants, measured and applied first. Then the module, the fake extensions and
  the tests: the plan, the two refusals, the three preconditions, the persisted record, the
  conditional delete, the rewritten-source plant, the `resolve` modes; the workflow with its
  main-only step; the sweep's tree widened.

### Phase 2: The switch (merge one)

- The two singular builders flipped; the SPEC-218 value tests rewritten; SPEC-219's today-equality
  assertions deleted and the archive-facts tripwire's docstring revisited; the browser row and its
  state deleted from all three renderers and both test files; the reservation test moved; Help read
  unchanged; the e2e rows re-keyed and the transitional row added. One PR.

### Phase 3: `report`, `copy`, the live checks, `finish`

- Run from `main`; wait out any in-flight execution the preconditions name; resolve any conflict
  through `resolve` and re-run `report` to zero; discharge every FR-004 row; then `finish`, and
  record both run ids.

### Phase 4: The narrowing (merge two)

- Old-anchor statements and elements out; the population test to single anchors; the sibling test
  deleted and the preservation sets rewritten; the plural builders shrunk to one element and every
  pair test rewritten; the accept list re-measured; the proved-empty row; the delivery doc's two
  points of no return and the arc note, including the reservation decision.
