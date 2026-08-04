# Spec: Refresh Table — In-Place Rebuild via `glue:UpdateTable`

**ID:** SPEC-149
**Status:** Draft
**Last Updated:** 2026-08-04
**Depends On:** SPEC-143 (the refresh branch, `load-table-definition`, the reconstructed partition keys), SPEC-144 (`diff-schema`, `apply-refresh`, the removal opt-in and the message layer this spec edits), SPEC-070 (`execute-ddl`, whose Athena DDL path this spec deliberately does **not** follow), SPEC-107 (`cpcommon`)

> **Reference:** `docs/architecture.md` → *Control Planes → Table Builder*; `docs/decisions.md` → *Removing a column requires an explicit opt-in*. Sequenced **between SPEC-144 and SPEC-145**, and that ordering is the point — see the Overview.
>
> **This spec changes ONE verb's mechanism and deletes more than it adds.** `apply-refresh` stops issuing DDL through Athena and calls `glue:UpdateTable` instead. The diff, the opt-in, the eligibility checks, the notifications and the state machine's shape are all unchanged.
>
> **The one thing to read before writing any code is FR-002.** `UpdateTable` replaces the WHOLE table definition — a `TableInput` missing a field does not leave that field alone, it clears it. Building the `TableInput` from SPEC-143's capture would therefore reintroduce the very metadata loss this spec exists to remove, because that capture never carried `Description` or `Owner`. The design is a **read-modify-write on the live table**, not a rebuild from the capture.
>
> **Rulebooks:** `docs/best-practices/lambdas/lambdas.md`.

## Overview

A refresh currently rebuilds a table by dropping it and creating it again. That works, and SPEC-144 made it as safe as the shape allows — the statements run back to back, both carry idempotency tokens, they share a poll budget, and a failure between them has its own wording. But the shape itself has costs that no amount of care removes: for a second or two the user's table **does not exist**, and the rebuilt catalog entry is a *new* entry, so the table's identity, its `Description`, its `Owner` and any Lake Formation grant made directly on it are gone.

Replacing the definition **in place** removes both costs at once. There is no window, because there is no moment when the table is absent. There is no metadata loss, because the fields the refresh does not own are never touched. And a failed update leaves the old definition standing, which retires the worst outcome SPEC-144 had to write wording for — *"the old table was removed and could not be rebuilt."*

It also stops the portal entrenching a pattern it would have to unpick later. Nothing here uses Apache Iceberg today, but a drop-and-recreate destroys snapshot history and time travel, which is most of the reason to adopt Iceberg at all. Choosing the in-place path now costs little; choosing it after users have been refreshing tables for months costs a migration.

**Why before SPEC-145.** Refresh is not reachable from the browser until 145. Until then the rebuild mechanism can change with no user-visible consequence and no data at risk. Afterwards, whichever mechanism users have been exercising is the one their tables carry the history of.

---

## Amends

- **SPEC-144 (FR-004, FR-006).** `apply-refresh` no longer issues `DROP TABLE` + `CREATE EXTERNAL TABLE`. The `drop_failed` and `recreate_failed` reason codes and their message bodies are **removed**, along with the replacement-window language, because neither state of the world can occur.
- **SPEC-144's two recorded exposures.** The fire-and-forget overlap window is **reduced, not closed** (FR-005 states the residue honestly); the "committed drop followed by exhausted retries notifies nobody" exposure is **retired**, because there is no committed destructive step to be silent about.
- **IAM.** `glue:DeleteTable` is **removed** from the table-builder execution role; `glue:UpdateTable` replaces it. The refresh path loses a destructive permission rather than gaining one.

---

## Scope

### In Scope

- **`apply-refresh` calls `glue:UpdateTable`** instead of running two Athena statements.
- **A read-modify-write on the live table** — `GetTable`, mutate only the fields a refresh owns, `UpdateTable` (FR-002).
- **Table versions are retained** so a bad refresh can be inspected and rolled back (FR-004).
- **The post-condition read stays**, unchanged in intent (FR-003).
- **IAM:** `glue:UpdateTable` added, `glue:DeleteTable` removed; Lake Formation needs no change (FR-006).
- **Message layer:** `update_failed` replaces `drop_failed` / `recreate_failed`; the "your table was removed" wording is deleted.
- **The Athena dependency on this path is removed** — the per-verb runner, the shared poll budget and the idempotency tokens all go with it.

### Out of Scope

- **Apache Iceberg.** Nothing here creates or manages an Iceberg table. This spec only avoids entrenching a pattern that would make adopting one worse.
- **The create path.** `execute-ddl` keeps running `CREATE EXTERNAL TABLE` through Athena (SPEC-070). Only the refresh changes.
- **The diff, the removal opt-in, the eligibility checks, the notifications' recipients or dedup.** All SPEC-143/144, all unchanged.
- **Closing the concurrent-refresh race outright.** FR-005 reduces it and states the residue; a real fix is a serialization change to the Pipe and belongs to its own spec.
- **Changing what `clone_definition` captures.** The capture is still used for the format cross-check and the diff; it simply stops being the source the apply rebuilds from.
- **Backfilling metadata onto tables already rebuilt by SPEC-144's DROP + CREATE.** What those tables lost is lost.

---

## Functional Requirements

### FR-001: `apply-refresh` updates the table instead of replacing it

#### Description

One Glue call replaces two Athena statements. The verb keeps its name, its position in the state machine, its notification and its `status: "refreshed"` outcome — a reader comparing the two versions should see the mechanism change and nothing else.

#### Acceptance Criteria:

- [ ] `apply-refresh` issues exactly one `glue.update_table` call and **no** `StartQueryExecution`. A test asserts the Athena client is never touched.
- [ ] `DROP TABLE` appears nowhere in the verb or its helpers; a test greps for it.
- [ ] The verb's output is unchanged: `status: "refreshed"`, `appliedColumnCount`, and the same single notification with the same dedup id (`{requestId}:refresh`).
- [ ] `refresh_athena.py` and the verb's use of `tbcommon.results` are **deleted**, not left unreferenced.
- [ ] A Glue throttle raises `TransientError` for the state-machine `Retry`; `EntityNotFoundException` raises `TerminalError("table_not_found")`.
- [ ] `AccessDeniedException` raises `TerminalError("update_failed")` with the raw text in the operator-only `detail` and never in the user's message (SPEC-106 FR-008).

### FR-002: The `TableInput` is a read-modify-write, never a rebuild from the capture

#### Description

**This is the requirement the whole spec turns on.** `UpdateTable` replaces the entire table definition: a `TableInput` that omits a field does not leave it alone, it **clears it**. So constructing the input from SPEC-143's captured definition would delete exactly what this spec exists to preserve — `clone_definition` never carried `Description` or `Owner`, and it deliberately strips `EXTERNAL` and `transient_lastDdlTime` from the parameters.

The verb therefore reads the live table immediately before writing it and mutates only what a refresh owns: the **columns**, and the **`projection.*` parameters** regenerated from the reconstructed partition keys. Everything else — storage descriptor fields, SerDe, input/output formats, partition keys, table type, every other parameter — is passed through exactly as Glue reported it.

#### Acceptance Criteria:

- [ ] The verb calls `glue.get_table` and builds its `TableInput` from the returned `Table`, stripping only the read-only fields Glue rejects on write (`DatabaseName`, `CreateTime`, `UpdateTime`, `CreatedBy`, `IsRegisteredWithLakeFormation`, `CatalogId`, `VersionId`, `FederatedTable` — **verify the exact set against the API during build; a rejected field fails the call, an unstripped one that Glue silently accepts is worse**).
- [ ] `StorageDescriptor.Columns` is replaced with the refreshed columns, carrying each surviving column's `Comment` (SPEC-144's behaviour, preserved).
- [ ] `Parameters` has every `projection.*` key **replaced** — old ones removed, regenerated ones added from the reconstructed partition keys — and every other key passed through untouched.
- [ ] `portal.managed` is re-asserted, so a table refreshed by this path stays marked.
- [ ] **A test asserts field preservation directly:** given a live table carrying `Description`, `Owner`, a `Parameters` entry no verb knows about, and a non-default SerDe parameter, the `TableInput` sent to Glue carries all four unchanged. This is the test that would have caught building from the capture.
- [ ] **A test asserts the columns really changed** — the same fixture's `Columns` reflect the diff. Preservation and mutation are asserted together, because a `TableInput` that changed nothing would pass a preservation-only test.
- [ ] `EXTERNAL` and `TableType` survive the round trip. A refresh must not convert an external table into a managed one — that would make a future drop destroy data.

### FR-003: The post-condition read stays

#### Description

`UpdateTable` returning success proves the call was accepted, not that the definition landed as intended. SPEC-135's lesson is unchanged by the mechanism: this plane's canonical failure was a verb that *completed* while the catalog did not agree.

#### Acceptance Criteria:

- [ ] After the update, the verb re-reads the table and compares the **case-folded column name set** against what it wrote; a mismatch raises `TerminalError("update_failed")`.
- [ ] The read is **terminal, never transient**, for the same reason as SPEC-144: a retryable verification would re-run the work it was verifying.
- [ ] A test proves the check bites, by returning a table whose columns differ from the ones written.

### FR-004: A refresh is reversible, because table versions are retained

#### Description

Glue keeps the previous definition as a table version unless asked not to. That is a genuine gain over drop-and-recreate — the pre-refresh schema remains inspectable, and a bad refresh can be reasoned about after the fact instead of reconstructed from logs.

#### Acceptance Criteria:

- [ ] The update does **not** skip archiving; the previous definition is retained as a Glue table version. A test asserts the call does not disable it, and the build **verifies the parameter's real name and default against the API** rather than trusting this prose.
- [ ] The retained version is named in the delivery doc as the manual rollback path, with the API call an operator would use.
- [ ] No automatic rollback is built. A failed update leaves the old definition in place, so there is nothing to roll back on the failure path; rolling back a *successful but unwanted* refresh is a user decision, not an automatic one.

### FR-005: The exposures SPEC-144 recorded are retired or reduced, and the residue is stated

#### Description

SPEC-144 recorded two exposures by decision. This spec closes one outright and shrinks the other. Neither claim should be made loosely — SPEC-144 FR-006 AC1 asserted a serialization guarantee that did not exist, and the correction is recent enough to be worth not repeating.

#### Acceptance Criteria:

- [ ] **The replacement window is gone.** There is no moment at which the table does not exist. A test asserts the verb issues no delete of any kind.
- [ ] **The "committed drop then silence" exposure is retired.** A failed update changes nothing, so an exhausted retry leaves the table exactly as it was — the outcome a silent failure would have hidden no longer differs from the starting state. The delivery doc records that this exposure is closed and why.
- [ ] **The concurrent-refresh race is REDUCED, NOT CLOSED, and this is stated rather than implied.** The Pipe still starts executions `FIRE_AND_FORGET`, so two refreshes on one database still overlap. What changes is the severity: neither run can now observe a missing table, and the failure mode degrades to last-write-wins between two definitions. Whether Glue offers a compare-and-set on `UpdateTable` (a version precondition) **must be established during build**: if it does, use it and narrow this further; if it does not, say so in the delivery doc rather than leaving the reader to assume.

### FR-006: IAM and Lake Formation

#### Acceptance Criteria:

- [ ] `infra/modules/table-builder/policies/execution.json.tftpl` gains `glue:UpdateTable` on the same `catalog` + `database/*` + `table/*/*` resources as the existing Glue actions.
- [ ] **`glue:DeleteTable` is REMOVED.** No verb on this plane deletes a table any more, and leaving the grant would keep a destructive permission the code no longer needs. A test greps the Lambda tree to confirm nothing calls it.
- [ ] The explicit `Deny s3:DeleteObject` (Sid `NoDataObjectDelete`) is **untouched**, and the comment beside it in `iam.tf` is updated: the "why a DROP is safe" reasoning is replaced with the stronger statement that the refresh path no longer deletes anything at all.
- [ ] **Lake Formation needs no change, and this is verified rather than assumed.** The table-level tag policy already grants `ALTER` (`infra/modules/analytics/lakeformation.tf`, `control_plane_tag_table`), which is the LF permission `UpdateTable` requires. A comment records it so the next reader does not go looking for a missing grant.
- [ ] `aws iam simulate-custom-policy` confirms the execution role can `glue:UpdateTable`, **cannot** `glue:DeleteTable`, and cannot delete any S3 object.

### FR-007: The message layer stops describing a rebuild

#### Acceptance Criteria:

- [ ] `drop_failed` and `recreate_failed` are removed from `tbcommon.messages._BODIES`; `update_failed` replaces them with wording that says **nothing was changed**, because nothing was.
- [ ] The `recreate_failed` wording — *"the old table was removed and the new one couldn't be created"* — is **deleted**, not reworded. It describes a state of the world this path cannot reach, and leaving it would be the message layer's version of dead code.
- [ ] A test asserts every **other** table-builder message is byte-for-byte unchanged, using the same literal expectation table SPEC-144 introduced.
- [ ] Every removed reason code is gone from the codebase, not merely unused: a test fails if `drop_failed` or `recreate_failed` appears anywhere outside this spec's own delivery doc.

### FR-008: Tests and lint

#### Acceptance Criteria:

- [ ] `ruff check lambdas/` and the Python suite pass; `tofu fmt -check -recursive` and `tofu validate` pass.
- [ ] Tests cover: the single `update_table` call and the absent Athena client; FR-002's preservation-and-mutation pair; `projection.*` replacement on a partitioned table with each key emitted exactly once; `portal.managed` re-asserted; `EXTERNAL`/`TableType` preserved; the post-condition mismatch; `table_not_found`; `update_failed` on access denied; a throttle raising `TransientError`; and the unchanged-message assertion.
- [ ] **A live check is owed and recorded in the delivery doc:** refresh a table that carries a `Description` and a column comment, and confirm from `GetTable` that both survive, the columns changed, and a previous table version exists. This is the only check that can prove the read-modify-write preserved what a unit test can only assert about a fake.

---

## Data Model

No change to the SQS envelope or the threaded state. `apply-refresh` stops emitting `ddl` (there is no statement) and continues to emit `status` and `appliedColumnCount`.

```python
# Threaded state after table-builder-apply-refresh — `ddl` REMOVED.
{
    "status": "refreshed",
    "appliedColumnCount": 16,
}

# Terminal reasons REMOVED by this spec:
#   drop_failed
#   recreate_failed
# Terminal reason ADDED:
#   update_failed
```

## API / Interface Contract

```python
# lambdas/table-builder-apply-refresh/apply_refresh.py

def _table_input(live_table: dict, columns: list[dict], partition_keys: list[dict]) -> dict:
    """The Glue TableInput for an in-place refresh: the LIVE table, minus the read-only
    fields Glue rejects, with columns and projection.* replaced.

    A READ-MODIFY-WRITE, never a rebuild from SPEC-143's capture. UpdateTable replaces the
    WHOLE definition, so any field this input omits is CLEARED — and the capture never
    carried Description or Owner and deliberately strips EXTERNAL. Building from it would
    delete exactly what this spec exists to preserve.
    """
```

## Environment Variables

None.

## File & Folder Structure

```
lambdas/
├── table-builder-apply-refresh/
│   ├── apply_refresh.py                # rewritten: Glue UpdateTable, read-modify-write
│   ├── refresh_athena.py               # DELETED — no Athena on this path
│   └── test_apply_refresh.py           # rewritten
└── table-builder-common/tbcommon/
    └── messages.py                     # - drop_failed / recreate_failed, + update_failed

infra/modules/table-builder/
├── policies/execution.json.tftpl       # + glue:UpdateTable, - glue:DeleteTable
└── iam.tf                              # the comment beside NoDataObjectDelete
```

## Implementation Phases

### Phase 1: The in-place update

- `_table_input`, the `UpdateTable` call, the post-condition read, `update_failed`.
- Delete `refresh_athena.py` and the DDL construction.
- **Tests:** FR-002's preservation-and-mutation pair first — it is the requirement most likely to be got wrong, and the one a fake can flatter.

### Phase 2: IAM, the message layer, and the sweep

- `glue:UpdateTable` in, `glue:DeleteTable` out, the `iam.tf` comment, the LF note.
- `update_failed` in, `drop_failed` / `recreate_failed` out, with the unchanged-message gate.
- **Tests:** the removed-reason grep and the byte-for-byte message table.

### Phase 3: Live check and closing out

- Run FR-008's live check: refresh a table carrying a `Description` and a column comment; confirm from `GetTable` that both survive, the columns changed, and a previous table version exists. Run FR-006's `simulate-custom-policy`.
- Completion ritual: `INDEX.md` status, delivery doc, a `decisions.md` amendment to the SPEC-144 entry (the apply is no longer a DROP + CREATE), and the one-line CLAUDE.md update. **No help-content change** — the feature is not user-reachable until SPEC-145.
