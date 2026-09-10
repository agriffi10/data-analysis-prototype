# Spec: Move the App-Managed Folders, Then Narrow

**ID:** SPEC-220
**Status:** Completed
**Last Updated:** 2026-09-09
**Depends On:** SPEC-219

## Overview

With both homes fenced (SPEC-219), the app-managed folders can actually move. After this spec a
space's root holds the user's own folders, `shared_tables/`, and one real `system_settings/` folder;
inside it sit `athenaresults/` and `archive/` — and the disclosure row is deleted, because the thing
it imitated now exists.

**`shared_tables/` does NOT move, and that is a correction made during the build.** The earlier
drafts moved all three. The tables in that folder were sent to this space by another one and the
user may edit them, so filing them under the folder the app manages says the opposite of what is
true — and it is the one of the three that carries no Deny anywhere, deliberately. It stays at the
space root. The consequence runs through the whole spec: **two folders move, not three**, no Glue
`LOCATION` points at anything the migration touches, and the migration is therefore an S3-only
operation with no catalog work, no Lake Formation probe and no `UpdateTable`. The
move is **two merges with a migration between them**, the shape SPEC-202 settled for a cutover:
first the writes switch, while both homes stay fully protected; then a CI-run migration copies the
existing objects across and, once every live check passes, deletes the sources; then the old-path
statements and rules come out and the old prefixes are proved empty positively. There are **two
points of no return**, and the spec names both: the migration's `finish` run for the objects, and
the second merge for the fences.

## Scope

### In Scope

- The write switch: `app_managed_prefix` / `appManagedPrefix` resolve to
  `{root}system_settings/{folder}/` **for a member of `MOVING_FOLDERS`**, and everything built on the
  **singular** follows — Athena output locations, receipt folders, results folders. A new shared
  table's `destPrefix` and `LOCATION` are unaffected, because `shared_tables/` is not a member. The
  plural builders and every rule on them are untouched, so both homes stay protected.
- The deploy role's three missing grants, in their own PR before the migration runs.
- A one-shot migration, a module run by a `workflow_dispatch` workflow under the deploy role, with a
  persisted copy record, preconditions on in-flight work, and a `resolve` mode for conflicts. It
  copies every existing object under the **two** moving folders to its new home and deletes a source
  only against the record. **It touches no catalog**: nothing it moves is a table's `LOCATION`.
- The browser: the group row deleted, `system_settings/` an ordinary-looking folder row with the
  protections SPEC-219 gave it, the two moving folders inside with their rules at depth two, and
  `shared_tables/` left at the space root with the rules it already had.
- Live checks between the switch and `finish`, against the four traps the arc names.
- The narrowing: old-anchor IAM statements and elements out, the plural builders shrunk to their one
  remaining element, the old prefixes proved empty, the Checkov accept list re-measured.

### Out of Scope

- **Moving `shared_tables/`.** It stays at the space root. A shared table is data another space
  sent this one and the user may edit it — it is the only one of the three app-managed folders with
  no Deny on either bucket, deliberately — so filing it under the folder the app manages would
  advertise a restriction that does not exist and imply the tables are not the user's. Consequences,
  all of them followed through: `MOVING_FOLDERS` holds two names and `SPACE_FOLDERS` still holds
  three, which is why they were separate tuples; a new shared table's `destPrefix` and `LOCATION`
  are unchanged; the migration re-points no catalog at all; and the `system_settings/shared_tables/`
  IAM anchors SPEC-219 added now guard a prefix nothing will ever write to. Those anchors and the
  `glue:UpdateTable` grant come out with the narrowing (FR-005) rather than in their own PR, since
  that merge already edits the templates.
- **The Glacier vault's layout.** `VAULT_ARCHIVE_SEGMENT` and every key in the archive bucket stay
  where they are; the FIFO golden vectors pass untouched. Only the user's receipt folder moves.
- **The admin bucket's `archive/*` scratch prefix** (`arcommon.plan.PREFIX`) and its lifecycle rule.
- **`user_settings/`, `saved_queries/`, `_data-quality-reports/`** and every other non-moving
  folder; they are neither moved nor swept.
- **Renaming the three folders**, or changing what a user may do inside them. `athenaresults/` stays
  visible, browsable and undeletable; `archive/` stays read-only; `shared_tables/` stays a folder
  the share pipeline fills.
- **Reserving the three retired names AT THE ROOT, or at any depth generally.** After the narrowing
  `alice/athenaresults/` is an ordinary user path — `validateFolderName` refuses `system_settings`
  everywhere, and the three folder names **only directly inside `system_settings/`**.
  That one exception was added during the build, on the user's decision, because the switch makes
  the prefix navigable AND writable — no IAM Deny names it — so a user could create
  `system_settings/archive/` themselves and every rule would then treat it as the app's: read-only
  inside, undeletable, unrenamable, unarchivable, permanently, at the exact path the restore dialog
  sends them to for their archive ids. **It covers the dialogs and nothing else**: uploads, pastes
  and plane-side moves create folders without calling the validator, so the collision stays
  reachable by those routes. That partiality is the reason the general version was rejected and it
  is recorded here rather than left for a reader to infer, because a courtesy read as a boundary is
  worse than no courtesy — the next author stops looking for the real one. Closing it properly is a
  root-aware, all-paths guard at the API or plane layer, and a spec of its own. An earlier draft reserved the three names too; it was dropped because the
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

`app_managed_prefix(root, folder)` returns `f"{root}{SYSTEM_SETTINGS_FOLDER}/{folder}/"` **for a
member of `MOVING_FOLDERS`, and `f"{root}{folder}/"` for anything else**, and `appManagedPrefix` its
twin, where `MOVING_FOLDERS` is `athenaresults` and `archive` — `shared_tables` is not a member and
does not move. The branch mirrors the plural's, and it is not optional: the singular takes a folder
name from a domain list as well as from this module's constants, and `rccommon.paths` calls it for every member
of `PROTECTED_DESTINATIONS` — five of whose eight members (`user_settings`, `_data-quality-reports`,
`_directory`, `_config` and `system_settings` itself) do not move. Unconditional, that call builds
`{root}system_settings/user_settings/`, a prefix nothing is stored under, and the refusal degrades in
silence because the same predicate's second leg matches the folder name at any depth. The two
builder tests that pin a non-moving name — `test_app_managed_cpcommon.py` for `user_settings` and
`appManagedPaths.test.ts` for the same — are the check that the branch is present, and they pass
**unchanged** through this FR. On the **TS** side the branch is parity rather than necessity: the
browser's singular builder has no production caller (`rccommon.paths` is the only one on either
side), so it branches to keep the two trees one design and to be correct for the first caller that
arrives, not to fix a live path. Because SPEC-218 routed every construction through them, the Athena
output location (`cpcommon.results`, `api/routes/athena.py`), a new shared table's `destPrefix` and
and the receipt folder
(`arcommon.paths.receipt_root`) all move with one edit per tree. A new shared table's `destPrefix`
and `LOCATION` (`table_share_check_target_absent`, `table_share_create_table`) go through the same
builder and are therefore **unchanged**, which is the branch doing its job on a real caller rather
than only on `user_settings`. **Nothing that SPEC-219 routed
through the plural is touched**: the excluders, the refusals and `_IGNORED_SUBTREES` read both homes
from literals, and re-pointing any of them to the singular here would drop protection of the old
home before `finish`. SPEC-219's today-equality assertions that the plural's first element equals
the singular are **deleted** here, since the two now legitimately differ, and the `ACCEPTED_`
tripwire on the three `archive` facts is revisited as its docstring asks: `RECEIPT_FOLDER` is still
spelled `archive` (the folder keeps its name; its parent changed), so the assertion stands and the
docstring records the revisit.

#### Acceptance Criteria:

- [ ] `app_managed_prefix("alice/", "user_settings") == "alice/user_settings/"` and its TS twin
      still — the existing rows, passing unchanged, which is what proves the singular branched
      rather than moving every name it is handed.
- [ ] `app_managed_prefix("alice/", "archive") == "alice/system_settings/archive/"` and
      `appManagedPrefix('alice/', 'archive') === 'alice/system_settings/archive/'`; the SPEC-218
      builder tests are rewritten to the new values and to nothing else.
- [ ] `app_managed_prefixes("alice/", "archive") == ("alice/archive/", "alice/system_settings/archive/")`
      still — asserted against the literal strings, not against the singular — and every SPEC-219
      parametrised old/new pair test passes unchanged, including the old-home rows; the diff touches
      no rule module.
- [ ] `results_location("b", "alice", "bob") == "s3://b/alice/system_settings/athenaresults/bob/"`;
      the API's Athena start route submits that output location for the verified claim; the
      the table-share destination is **unchanged** at `{name}/shared_tables/{table}/`; a receipt root is
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

**The grants first, in their own PR.** The deploy role holds `s3:*` on both space buckets and the
admin bucket, which covers every S3 call below (listing, `HeadObject`, `CopyObject` with the tagging
reads and writes `TaggingDirective=COPY` needs, `DeleteObjects`, the record). It lacks
`states:ListExecutions` on the archive and table-share state machines, and
`athena:ListQueryExecutions` / `athena:BatchGetQueryExecution` on the one workgroup. Each is measured
with `simulate-custom-policy` and landed before Phase 3, on the register's rule. IAM simulate cannot
see Lake Formation; the deploy role is a data-lake admin, so the first `update_table` **is** the LF
probe: the module re-points one table, reads it back, and only then loops.

**The module.** `scripts/migrate_system_settings.py`, run by `.github/workflows/migrate-system-settings.yml`
(on `backfill-ever-active.yml`'s precedent for a one-shot: manual, a `mode` input, a concurrency
group, `PROJECT_NAME`/`ENVIRONMENT` from repository variables to derive the two space buckets, the
admin bucket, the archive and table-share state-machine ARNs and the workgroup; unlike the
precedent it carries an explicit step that fails on any ref but `main`, and `timeout-minutes: 360`).
It imports the four folder names from `cpcommon.app_managed` through the `sys.path` shim
`scripts/generate_api_contract.py` already uses — never as literals — and the sweep's Python tree
gains `scripts/` so a literal there is refused, with the sweep's own module and corpus excluded by
path (they spell `"archive"` as the rule they enforce, and its filename-prefix exclusions do not
cover them). It enumerates every space by listing each bucket root with `Delimiter="/"`, skipping
the user-space bucket's `_config/` and `_directory/` (they hold no space). Because IAM no longer
bounds it, the module **itself** refuses, as `outside_migration_scope`, to read, copy or delete any
key not under `{space}/{folder}/` for the two moving folders; a test plants it and asserts the code.
There is no catalog refusal because there is no catalog work: `shared_tables/` does not move, so no
table's `LOCATION` points at anything this module touches.
**Both are correctness guards on this script, and neither is an authorization boundary.** They bind
`scripts/migrate_system_settings.py` and nothing else, and they deny nobody who reaches the deploy
role by another path. The sentence above says IAM no longer bounds the module, which is true and is
precisely why the distinction has to be written down: read as a fence, these refusals leave the next
author believing a bound exists where none does.

**The record outlives a run.** `run_id` is the workflow run's `GITHUB_RUN_ID`, written to
`$GITHUB_STEP_SUMMARY` (the precedent's channel) so the operator can copy it. `copy` persists the
record to the admin bucket at `migration/system-settings/{run_id}.json` — a prefix no lifecycle rule
expires — **incrementally, every 500 keys**, so a run cut off by the runner leaves a record a re-run
extends. Every mode but `report`-without-an-id takes `run_id`, and a `copy` given one **extends** that
record rather than opening a new one. Per source key the record holds the source's `ETag` and
`LastModified` and `copied_etag`: the `CopyObjectResult.ETag` the copy returned, or, for a key the
copy skipped because the destination already existed, the destination's own `HeadObject` ETag.
"Already present" means exactly *destination ETag equals `copied_etag` in the record*; a destination
that exists with no record, or with a different ETag, is a **conflict** — source-versus-destination
ETag comparison is never used, because a multipart source carries an `…-N` ETag a single `CopyObject`
never reproduces.

**Six modes.**
- `report [run_id]` — prints, per bucket and space, the keys and bytes under each old prefix, the
  and — reading the record when given one — `conflicts`,
  `oversize`, `absent` and `refused`. Writes nothing.
- `copy run_id?` — refuses to start while any **precondition** fails, naming the execution: an
  archive-plane or table-share execution `RUNNING` (`ListExecutions` on each machine), or an Athena
  execution in the workgroup non-terminal (`ListQueryExecutions`, paged, which lists the last 45
  days newest first). A restore computes its receipt key at validate time and rewrites it hours
  later, a share computes its `destPrefix` at validate time and writes data and a `LOCATION` later,
  and a query started before the switch lands its CSV at the old location minutes later; the
  operator waits for the execution to end (a restore is 3–5 hours) and re-dispatches. It then
  copies, passing the source's `StorageClass` explicitly (a `CopyObject` lands in `STANDARD`
  otherwise) and leaving `MetadataDirective` and `TaggingDirective` at `COPY` (passing `ContentType`
  would force `REPLACE` and drop user metadata); a key over 5 GB is copied with `UploadPartCopy` in
  1 GiB parts and listed under `oversize` for the record, not refused. It re-points the tables with
  `SkipArchive=False` (the refresh verb's choice: the retained version is the rollback), one first
  and read back as the LF probe. It is idempotent: a second `copy` with the same `run_id` copies zero
  keys and re-points zero tables.
- `resolve run_id key keep=source|destination` — for a conflict: `keep=source` re-copies the source
  over the destination and records the new `copied_etag`; `keep=destination` marks the key so
  `finish` deletes its source without a match. Either way the next `report run_id` shows one fewer
  conflict. Each resolution is logged in the record and named in the delivery doc. For a table
  re-shared after the switch while its old copy still existed, keep the destination — it is the
  newer share.
- `verify run_id` — `HeadObject` and `GetObjectTagging` on a sample of N recorded keys per bucket
  (default 20, every storage class present at least once) and prints source-versus-destination
  storage class, content type, user metadata and tags side by side. The vehicle for FR-004's
  attribute row.
- `finish run_id` — refuses without a record or while `conflicts` is non-empty. Re-`HeadObject`s both
  sides of every recorded key; refuses (lists under `refused`, continues, exits non-zero at the end) a
  key whose source no longer matches its record or whose destination no longer matches `copied_etag`;
  lists under `absent` a source a user has since deleted (the object survives at the new home); deletes the rest with the recorded source `ETag` on the
  `ObjectIdentifier`, in batches of at most 1000, reading the per-item `Errors` array. A per-item
  `PreconditionFailed` / `ConditionalRequestConflict` for a key whose HEAD just verified is recorded
  under `refused`, never retried blind — `focommon.delete` records that conditional delete is
  unverified live on these buckets, so **the head re-verify is the proven guard** and the identifier
  ETag is belt; this run does not discharge that owed row, which needs a planted mismatch. `finish`
  is re-runnable with the same `run_id`: an already-deleted source lands under `absent`.
- `prove-empty` — FR-005's fail-closed loop over every space and the two moving folders, from the same
  identity; the vehicle for the proved-empty row.

**Keys that arrive at an old prefix between `copy` and `finish`** — a user upload into
`alice/shared_tables/…` (nothing denies it), or a re-share of a table whose old copy still exists —
are not in the record and survive `finish`; `prove-empty` then finds them. The remedy is the same
run: `copy run_id` again (extends the record), `resolve` the re-share keeping the destination,
`finish run_id` again.

#### Acceptance Criteria:

- [ ] The grants PR: `states:ListExecutions` on the two machines, `athena:ListQueryExecutions` and
      `athena:BatchGetQueryExecution` on the workgroup — each measured `allowed` with
      `simulate-custom-policy` and `implicitDeny` on a neighbour, applied green before Phase 3, with
      the Checkov plan scan re-read.
- [ ] The module refuses a key outside the two moving prefixes as `outside_migration_scope`; a test
      plants it and asserts the code. The fakes in `lambdas/shared-space-common/fakes.py` are extended —
      `head_object`, `Delimiter`/`CommonPrefixes` on `list_objects_v2`, a `CopyObjectResult.ETag` and
      metadata/tagging/storage-class carry on `copy_object`, `upload_part_copy`, `ETag` on a delete
      identifier — from the S3 contract rather than from
      the module, and the module's tests live under `lambdas/` as
      `lambdas/test_migrate_system_settings.py`, importing the script through the same shim.
- [ ] `report` with no record lists keys, bytes and tables per bucket and space and writes nothing;
      `report run_id` also lists `conflicts`, `oversize`, `absent` and `refused` from the record.
- [ ] `copy` refuses to start while any precondition fails, naming the execution; writes the record
      every 500 keys and the run id to the step summary; passes `StorageClass` through and leaves
      both directives at `COPY` (fake-asserted); copies a planted 6 GB source in parts; re-points one
      table and reads it back before the rest; a second `copy run_id` copies zero keys and re-points
      zero tables; and a destination present with a matching `copied_etag` is skipped while one with
      no record is a conflict (both planted).
- [ ] `resolve` with `keep=source` re-copies and updates `copied_etag`; with `keep=destination`
      marks the key so `finish` deletes its source; the next `report run_id` shows one fewer conflict.
- [ ] `verify run_id` prints the side-by-side attributes for the sample; the fakes carry enough for
      the test to assert the columns, and the real-S3 preservation is FR-004's row.
- [ ] `finish run_id` refuses without a record or while `conflicts` is non-empty; deletes only keys
      whose source and destination both re-verify; lists `absent` and `refused` and exits non-zero
      when `refused` is non-empty; sends the recorded source `ETag` on each identifier; batches at
      most 1000 and reads the per-item `Errors` array; a test plants a source rewritten after the
      copy and asserts it lands in `refused`, not deleted; a second `finish run_id` lists the deleted
      sources under `absent` and deletes nothing.
- [ ] The module issues **no** `update_table` at all, asserted on the Glue fake, because nothing it
      moves is a table's location; it joins `mypy`'s file list entering at zero (a
      local gate — CI runs no mypy), carries no inline comments and a docstring per function.
- [ ] The order is fixed and recorded in the delivery doc with the `copy` and `finish` run ids:
      grants PR applied; FR-001 merged and `Deploy Lambdas` green on the merge sha
      (`scripts/watch_ci.py --branch main`), since the preconditions cannot see a fleet still on the
      pre-switch image; `report`; the FR-004 `count(*)` **before** the re-point; `copy`; the FR-004
      checks including `verify`; `finish`; then FR-005. The `finish` run is the point of no return for
      the objects.

### FR-003: The browser shows the real folder and drops the row that imitated it

#### Description:

`SystemFolderGroupRow`, `partitionSystemFolders`, `SYSTEM_GROUPED_FOLDERS`, `systemFolderGroupCaption`
and `FileBrowser`'s `systemExpanded` state are deleted, from `FileListTable.tsx`, `FileListMobile.tsx`
and `FileBrowser.tsx` alike, with `systemFolders.ts`, `SystemFolderGroupRow.tsx`, their tests, the
group `describe` in `fileBrowser.a11y.test.tsx` and the seven group tests in `FileBrowser.test.tsx`;
the four comment references in `protectedFolders.ts` are rewritten. `system_settings/` is listed as
a folder row like any other, sorted among the user's folders, with the refusals SPEC-219 gave it;
opening it lists the two moving folders, each with the rules it had at the root now at depth two;
`shared_tables/` stays at the space root with the rules it already had.
`validateFolderName` keeps refusing `system_settings` at every depth as it does today, importing
`SYSTEM_SETTINGS_FOLDER` from `lib/appManagedPaths`, with its docstring and message rewritten to say
the folder is the app's rather than that the list uses the name, and its reservation test moved from
the deleted `systemFolders.test.ts` into `fileBrowser.service`'s tests. **Between merge one and
`finish`** the root also shows the two old folders as ordinary-looking rows, still refusing every
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
      reason) — the same rows the e2e guide has for them
      at the root today, re-keyed to the new location in `docs/testing/e2e.md`, whose
      `system_settings` row-behaviour row is deleted; and a row for the transitional root (both homes
      listed, both refusing) is added and marked as retired after `finish`.
- [ ] The two phrases this criterion is about need no edit, read at review: the archive entry's
      "under `system_settings` → `archive`" and the file-browser entry's "gathered under
      `system_settings`" are now literally true, and `RestoreArchiveDialog.tsx` is untouched.
      **`helpContent.ts` takes one edit the criterion did not anticipate**: the same sentence also
      said the folder sits "below your own folders", which was true of a row that always rendered
      last and is false of an ordinary row that sorts — `system_settings` lands above a folder named
      `taxes`. Help documents only what is shipped, so the clause is corrected rather than left.
      A pre-switch archive id is at the depth-one `archive/` until `finish`, which neither surface
      says; that window is carried by the transitional row in `docs/testing/e2e.md` rather than by
      wording that would have to be removed again afterwards.

### FR-004: Live checks between the switch and `finish`, while every step is still reversible

#### Description:

With FR-001 deployed and `copy` run, both homes hold the objects and both are fenced. The four traps
the arc names are exercised against the account; only after every row is discharged does `finish`
run. The CLI rows run as a workflow step under the deploy role; the IAM rows use
`simulate-principal-policy` from the operator's own CLI identity, as SPEC-219 FR-004 does — the two
identities differ, and the rows say which.

#### Acceptance Criteria:

- [ ] **Glue `LOCATION` — nothing to check, and that is the point.** `shared_tables/` does not
      move, so no table's location changes and the pre-`copy` `count(*)` is not needed. What IS
      asserted is the absence: a shared table's `LOCATION` still reads `{space}/shared_tables/…`
      after `finish`, and the migration's run summary reports zero catalog writes. Recorded as a row
      so a later reader does not assume the check was skipped rather than made unnecessary.
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
      and tags — `verify run_id`'s side-by-side sample, read from the run's summary — the attribute
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
(**six** plane templates — `archive`, `data-quality`, `file-ops`, `results-conversion`,
`table-builder` and `table-share`; results-conversion joined the population table on a rebase, which
is how an earlier count of five survived into this draft) comes out; the `…SystemSettings` Sids keep
their names, because
`archiveWriteLock.test.ts` keys on them, and its matcher returns to one Sid per bucket; SPEC-219's
sibling-pair test is deleted, since with no old-anchor statement left it can pass on nothing;
`test_portal_role_preservation.py`'s gained and lost sets are rewritten to the end state. The
population test's expected pairs shrink to the `system_settings/` anchors — and SPEC-221's plane
**has** landed its own `athenaresults` template (`2a526959`, #659), so results-conversion is simply
one of the six above rather than the conditional extra row an earlier draft allowed for.
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

- [x] The population test's expected table has exactly one entry per file per folder and the two
      admin-bucket entries unchanged; it fails if any old-anchor Resource survives (planted one,
      watched it name the file, reverted).
      **"all anchored `system_settings`" was wrong when this was written**, and the criterion four
      bullets down says so: `shared_tables/` never moved, so `results-conversion` and `table-share`
      each keep a depth-one `*/shared_tables` entry. Built to the sentence as first written, the
      merge would have deleted two Denies the Out of Scope list protects.
- [x] `app_managed_prefixes(root, f) == (app_managed_prefix(root, f),)` for a member and
      `appManagedPrefixes` its twin.
      **"and no rule module" was FALSE, and this is the finding the merge turned up.** Five rules
      mirror a shared-bucket Deny with a hand-written any-depth segment scan keyed on the bare
      folder NAME, fed by no builder: `writeLockedPrefix.ts`,
      `focommon.protected._is_at_or_below`, `focommon.delete.assert_item_deletable`,
      `apicommon.protected._is_write_locked` and `arcommon.plan._assert_deletable_folder`. The Deny
      now reads `*/system_settings/archive/*`, so each was refusing writes and deletes IAM permits
      in a user's own folder — over-refusal, which fails safe and is therefore the kind nothing
      reports. All five now go through a new builder, `app_managed_segments`, so the rule has one
      home the way the prefixes do. The clause is replaced rather than struck because a reader
      checking whether the narrowing was confined to the builders deserves the real answer. every SPEC-219 pair test is rewritten
      to the single location, and the archive/file-send/file-ops refusal tests for a depth-one
      `alice/archive/x` now expect the key to be treated as an **ordinary** user path;
      `_IGNORED_SUBTREES` is asserted as the two-tuple `("system_settings/athenaresults/", "user_settings/")`;
      the data-quality first-segment refusal for `athenaresults` is asserted as the named exception.
- [ ] **The grants come back out**, in this merge — `athena:ListQueryExecutions`,
      `athena:BatchGetQueryExecution` and both `states:ListExecutions`. They were granted for a
      one-shot that has now run, and lifetime is the axis available: this merge already edits IAM
      templates and re-measures the accept list, and the removal cannot deadlock, because a refresh
      reads policies with `iam:GetPolicyVersion`, which the role holds independently. The precedent
      is the layer grants that "outlived the resources by exactly one apply … and came off
      immediately after" (`infra/modules/base/README.md`).
- [ ] **`glue:UpdateTable` comes out too, and it was never used.** It was granted to re-point shared
      tables; `shared_tables/` then turned out not to move, so nothing ever called it. Removing it
      matters more than the others, not less: Lake Formation adds no restraint here — the deploy role
      is a data-lake admin holding `lakeformation:GrantPermissions` on `*`, so it can self-grant
      `ALTER` on any table — which made the IAM action list the only fence over re-pointing any
      table's `LOCATION`, and a re-pointed `LOCATION` makes the portal serve another space's data
      through credential vending, silently. A capability granted for work that no longer exists is
      the easiest kind to leave behind.
- [ ] **The `system_settings/shared_tables/` anchors come out of the templates**, in the same merge.
      SPEC-219 added them additively for a move that is no longer happening, so they guard a prefix
      nothing will ever write to; the population test's expected pairs drop them, and
      `shared_tables/` keeps exactly the depth-one anchors it always had.
- [ ] `checkov` on the deploy plan: zero unaccepted findings and zero stale acceptances; the accept
      list's diff, if any, is in the PR with a one-line disposition per line.
- [ ] Proved empty by the workflow's `prove-empty` mode under the deploy role, recorded in
      `docs/testing/owed.md` with the run id and the date: for every prefix a `Delimiter="/"` listing
      of each bucket root returns (skipping `_config/` and `_directory/`), `list_objects_v2` with
      `Prefix={space}/{folder}/, MaxKeys=1` for the two moving folders returns no `Contents`. The loop
      fails closed on any error — an empty result from a failed call is not an empty prefix — and a
      space that still holds a key blocks the merge; the remedy is another `copy` / `finish` round
      with the same run id (FR-002).
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

Mode = Literal["report", "copy", "resolve", "verify", "finish", "prove-empty"]

class Recorded(TypedDict):
    source_etag: str
    source_last_modified: str
    copied_etag: str            # CopyObjectResult.ETag — or the destination's HEAD ETag for a key the
                                #   copy skipped as already present; what finish re-verifies against
    resolution: Literal["", "keep-source", "keep-destination"]

class Record(TypedDict):        # persisted at s3://{admin bucket}/migration/system-settings/{run_id}.json,
                                # written every 500 keys; run_id is GITHUB_RUN_ID, printed to the step summary
    run_id: str
    started: str
    keys: dict[str, Recorded]   # per source object, keyed "{bucket}|{key}" — a space name is unique
                                #   WITHIN a bucket and not across the two, so a user `alice` and a
                                #   shared space `alice` can each hold the same key; keyed by the
                                #   key alone they collapse, and the run then reports a deletion it
                                #   did not make and omits one it did
    # No `tables` register: the migration writes no catalog, because shared_tables does not move
    conflicts: list[str]
    oversize: list[str]
    oversize_done: list[str]    # copied in parts; informational
    absent: list[str]           # filled by finish: sources gone before deletion
    refused: list[str]          # filled by finish: a HEAD or a delete that no longer matched the record
```

## File & Folder Structure

```
infra/modules/base/policies/github-actions-deploy*.json.tftpl   # UpdateTable/GetTable, ListExecutions,
                                                                #   ListQueryExecutions/BatchGet — own PR
.github/workflows/migrate-system-settings.yml     # workflow_dispatch: report | copy | resolve | verify |
                                                  #   finish | prove-empty; main-only step; timeout 360;
                                                  #   run_id / key / keep inputs; names from PROJECT_NAME/ENVIRONMENT
scripts/migrate_system_settings.py                # the module; refuses anything outside the two prefixes
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
  the tests: the plan, the scope refusal, the three preconditions, the persisted record, the
  conditional delete, the rewritten-source plant, the `resolve` modes; the workflow with its
  main-only step; the sweep's tree widened.

### Phase 2: The switch (merge one)

- The two singular builders flipped, branching on `MOVING_FOLDERS`; `shared_tables` taken out of
  that tuple and the migration's catalog work deleted with it; the SPEC-218 value tests rewritten;
  SPEC-219's today-equality assertions replaced and the archive-facts tripwire's docstring revisited;
  the browser row and its state deleted from all three renderers and both test files; the
  reservation test moved and extended to the app's folders inside `system_settings/`; Help corrected
  where the row's positioning made it false; the e2e rows re-keyed and the transitional row added.
  One PR.

### Phase 3: `report`, `copy`, the live checks, `finish`

- Run from `main` after `Deploy Lambdas` is green on the switch sha; wait out any in-flight
  execution the preconditions name; `copy`; `resolve` any conflict and re-run `report run_id` to
  zero; `verify`; discharge every FR-004 row; then `finish`, and record both run ids. No pre-`copy`
  `count(*)` is needed — no table's `LOCATION` moves.

### Phase 4: The narrowing (merge two)

- Old-anchor statements and elements out; the population test to single anchors; the sibling test
  deleted and the preservation sets rewritten; the plural builders shrunk to one element and every
  pair test rewritten; the accept list re-measured; the proved-empty row; the delivery doc's two
  points of no return and the arc note, including the reservation decision.
