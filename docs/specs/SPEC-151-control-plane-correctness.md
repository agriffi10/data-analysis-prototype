# Spec: Control-Plane Correctness — Single-File Checks, Teardown Integrity & DDL Escaping

**ID:** SPEC-151
**Status:** Completed
**Last Updated:** 2026-08-05
**Depends On:** SPEC-110 (`dq_inspect_source` and the manifest this spec re-scopes), SPEC-112 (the data-quality report shape whose internal consistency FR-001 restores), SPEC-054 (the shared-space teardown acceptance criterion FR-003 finally meets), SPEC-125 (`shared-space-common`, `casio`), SPEC-107 (`cpcommon`), SPEC-070 (`cpcommon.ddl` and the create path FR-006 escapes)

> **Reference:** from the 2026-08-05 codebase audit. Six correctness defects in the Python control planes, none of which needs new infrastructure, a new Lambda, a new IAM action or a new env var. **If a task here starts editing `infra/` beyond nothing, it has gone wrong** — the one finding that does need new states and a new verb is SPEC-152, deliberately split out because CLAUDE.md's infra rule gives it a different risk profile.
>
> **Two of these are data-integrity defects, not cosmetics.** FR-001/FR-002 can hand a user a report that says `verdict: "clean"` about data it never read. FR-003 can free a shared-space name while another tenant's objects are still under it. Everything else is a smaller correctness gap.
>
> **The house pattern to copy already exists in the repo, in every case.** The browser's `deleteInBatches` (`fileBrowser.service.ts:315,322`) already sets `Quiet: false` and iterates `response.Errors` — FR-003 is that, in Python. `dqcommon/index_store.py:128-138` and `log-sweep/log_sweep.py:167-175` already handle the racing 409 **and explain why** — FR-005 is that, in `casio`. `cpcommon.ddl.literal()` already exists at `ddl.py:110` and is already used for column comments — FR-006 is that, applied to the two places that skipped it. Prefer aligning with the existing twin over inventing a new shape.
>
> **FR-001 and FR-002 need a live check.** They are the only items in this spec whose fix cannot be fully proven by unit tests, because the bug is about what Athena does with a `LOCATION` and what S3 does with a prefix. Phase 5 is not optional.

## Overview

The Lambda fleet is in good shape — 1745 tests, 96% coverage, deliberate fakes, and broad `except` clauses that all log or re-raise. What the audit found is a set of individually small defects that share one shape: **a guard or a helper exists, and one call site does not use it.**

Two of them reach the user. A data-quality check run against a *single file* silently profiles the file's entire parent folder, because an Athena external table reads its `LOCATION` recursively — so `rowCount` and every per-column figure describe the folder while `rowCountsByFile` describes the one file, and the delivered report is internally inconsistent. Worse, the single-file listing prefix is a plain prefix match, so a check on `data.csv` also matches `data.csv.gz`; when it does, the table gets built over an empty path and the report comes back `clean` with `rowCount: 0`. A user reading that report would conclude their data is fine when nothing was examined.

The rest are integrity gaps with narrower blast radii but real consequences: a shared-space teardown that discards the per-key errors S3 returns with HTTP 200 and then frees the name for reuse; a roster CAS that re-reads the record and then overwrites the one field it exists to protect with a stale list; a conditional-write predicate that misses the 409 its own two twins handle; and DDL that interpolates user-supplied partition values into `TBLPROPERTIES` without the escaper sitting in the same module.

None of this changes a user-facing feature. The outcome is that a check reports on what the user selected, a teardown that fails does not release the name, concurrent roster edits do not lose each other, and a folder name containing an apostrophe stops breaking the catalog.

---

## Scope

### In Scope

- **Constraining a single-file data-quality check to the selected file**, and fixing the listing prefix that lets siblings in.
- **Surfacing per-key failures** from `delete_objects` and `batch_delete_table` in shared-space teardown, before the registry record is deleted.
- **Making `save_members` a delta under CAS**, and stopping it from reverting a `deleting` status.
- **Adding the racing 409 to `casio.is_precondition`.**
- **Rendering DDL literals through `literal()`** for `TBLPROPERTIES` values and `LOCATION`.
- **Completing partition-key validation** — `format` for `date`, element types for `range`/`values`, and `digits` — plus normalising the browser's `intervalUnit` to the key the renderer reads.
- **Classifying Glue's transient codes on the read paths**, not only in `apply-refresh`.
- **Two small hygiene fixes**: `clients.jwks(url)` caching per URL, and `normalize_members` being computed once per add.
- **A live verification pass** for FR-001/FR-002.

### Out of Scope

- **Adding failure notification for pre-verb failures** — that is SPEC-152 (new ASL states, new verb, deploy-role IAM).
- **Meta-test and fake improvements** — the pagination fakes that would let FR-003 be unit-tested end to end are SPEC-153. FR-003 here ships with the tests the current fakes permit, and SPEC-153 deepens them. This ordering is deliberate: the fix should not wait on the harness.
- **Consolidating the three CAS implementations** into `cpcommon` — SPEC-156. FR-005 fixes the predicate **in place**; do not move it.
- **Consolidating `failure_message`, `results_location`, the duplicated JWKS verifier or the SQS envelope parser** — SPEC-156.
- **Any change to the report schema, the notification message set, or the index format.**
- **The concurrent-refresh race on `glue:UpdateTable`.** Reduced from the browser side by SPEC-150 FR-003; a real fix is a Pipe serialization change and its own spec.

---

## Functional Requirements

### FR-001: A single-file check profiles only the selected file

#### Description

`dq_create_temp_tables.py:71-74` promotes the table `LOCATION` to the parent folder when the target is one file, because Athena needs a prefix. But Athena reads a `LOCATION` **recursively**, so the typed and raw-line temp tables cover every file in that folder. `report.py:507,515,523` derives `rowCount`, `duplicateRows` and every per-column `missing`/`not_<cast>` count from the folder-wide total row, while `report.py:281-284` reconciles `rowCountsByFile` to the manifest — so the delivered report satisfies neither the user's selection nor its own arithmetic. The docstring currently asserts the opposite.

#### Acceptance Criteria

- [ ] For a single-file target, every figure in the report describes **only that file**: `rowCount`, `duplicateRows`, and each column's `missing` and `not_<cast>` counts.
- [ ] `rowCount == sum(rowCountsByFile.values())` holds for a single-file target. Asserted by test.
- [ ] The implementation constrains the query rather than the location — a `"$path"` predicate in `dqcommon.sql`'s profile and ragged builders when the manifest holds exactly one file whose key is not the folder itself. The `LOCATION` may remain the parent, since Athena requires a prefix.
- [ ] The `"$path"` value is matched against the same `s3://bucket/key` form the manifest is keyed to. If that form is not identical, the mismatch is resolved here and the resolution recorded — it is the same assumption SPEC-142's owed live run rests on.
- [ ] A folder target is **unchanged** — same numbers as before, asserted against the existing fixtures.
- [ ] The stale docstring at `dq_create_temp_tables.py:68-74` (which claims the parent-folder location "is still correct here because the manifest listed exactly that one object") is corrected. It must not survive.
- [ ] The test that currently pins the parent-folder choice is updated to pin the new behaviour, not deleted silently.

### FR-002: A single-file listing matches the object, not the prefix

#### Description

`dq_inspect_source.py:143-145` returns a bare `location` for the file branch, and `list_objects_v2` is a **prefix** match — so a check on `alice/data.csv` also lists `alice/data.csv.gz`, `alice/data.csv.bak`, `alice/data.csv2`. The same docstring (`:118-121`) reasons carefully about exactly this hazard, but only for the folder branch. When a sibling matches, `keys == [prefix]` goes false, FR-001's parent-promotion does not apply, the table is built at `s3://…/alice/data.csv/` over nothing, `GROUPING SETS` still emits a total row so `MissingProfileError` never fires, and `report.py:539` returns `verdict: "clean"` with `rowCount: 0`.

#### Acceptance Criteria

- [ ] A single-file target's manifest contains **exactly** the selected key, never a sibling sharing its stem.
- [ ] Given objects `data.csv`, `data.csv.gz` and `data.csv2` under one prefix, a check on `data.csv` manifests exactly one key. Asserted by test.
- [ ] The unsupported-format refusal can no longer name a file the user did not select. Asserted by test with an unsupported sibling present.
- [ ] A check whose selected key does not exist still fails as it does today — the fix must not turn a missing object into an empty-manifest success.
- [ ] No `clean` verdict can be produced from an empty profile: `report.py` raises or refuses where `rowCount` is 0 **and** the manifest is non-empty, rather than returning `clean`. If that guard belongs elsewhere, it is placed there and the reasoning recorded.
- [ ] The folder branch is unchanged.

### FR-003: Teardown surfaces per-key failures before the name is freed

#### Description

`teardown.py:34` discards the return value of `delete_objects`, which returns HTTP 200 with a per-key `Errors` array; `:84` does the same for `batch_delete_table`. `delete_space.py:44` then runs `reg.delete(space)` — commented "LAST — the name is now free to reuse". A partially-failed teardown therefore releases the name with objects still under `{name}/`, so the next space created with that name inherits another tenant's data. **SPEC-054 states as an acceptance criterion that teardown leaves "never a dangling … half-deleted resource."**

#### Acceptance Criteria

- [ ] `delete_shared_prefix` collects `response["Errors"]` from every `delete_objects` call and raises if any are present, carrying the failed key count (never the full key list — the field rule).
- [ ] `drop_database` does the same for `batch_delete_table`'s per-table errors.
- [ ] A raise leaves the registry record **intact**, so the name is not freed and the caller records a terminal `failed` as it already does. Asserted by test.
- [ ] `delete_objects` is called with `Quiet: false` if that is required to receive the `Errors` array, matching the browser's `fileBrowser.service.ts:315`.
- [ ] A fully successful teardown behaves exactly as today, including freeing the name.
- [ ] Both `delete-space` and `forget-space` inherit the guarantee, since both call the same helpers.
- [ ] The test uses a fake that can return partial errors. If the current `fakes.py` cannot express that, it is extended here — this is the minimum fake work FR-003 needs, and it does not wait on SPEC-153.

### FR-004: `save_members` applies a delta, and never revives a deleting space

#### Description

`registry.py:202-231` re-reads the record under CAS and then assigns `record["members"] = members`, where `members` was computed by the caller from the **stale** snapshot in `event["registry"]` (`add_members.py:33,73`; `remove_members.py:30,48`; `leave.py:34,50`). Two overlapping requests on one space last-write-wins on the roster — a concurrent remove reinstates a just-added member. Nothing serializes them: `shared-spaces/pipe.tf:30` is `FIRE_AND_FORGET`, the group id is the global constant `'shared-space'`, and `casio.py:5-7` says so outright. Separately, `:216` sets `record["status"] = "active"`, which can revert a `deleting` status set by `delete_space.py:36`.

#### Acceptance Criteria

- [ ] `save_members` takes a **delta** (`add` and/or `remove`) rather than a computed member list, and derives the new roster from `existing["members"]` **inside** the CAS `apply` callback.
- [ ] An add and a remove issued concurrently on one space both take effect, in either interleaving. Asserted by a test that drives two `apply` passes against a store whose ETag rotates between them.
- [ ] `save_members` no longer sets `status` unconditionally. A space in `deleting` is not returned to `active` by a concurrent membership write. Asserted by test.
- [ ] The three callers (`add_members`, `remove_members`, `leave`) pass deltas; none computes a full roster from `event["registry"]`.
- [ ] Owner semantics, the `pending`/`active` join status (SPEC-073) and the roster fan-out (SPEC-075) are unchanged.

### FR-005: `casio.is_precondition` recognises the racing 409

#### Description

`casio.py:36-38` matches only `PreconditionFailed`/`412`. Both twins handle 409 and document why — `dqcommon/index_store.py:128-138` ("treating the 409 as a hard error would drop the FIRST run") and `log-sweep/log_sweep.py:167-175`. The shared-space copy guards three `If-None-Match: *` creates: `registry.py:112-115` (`reserve`), `registry._put:68-69`, and `cache.py:79-83`.

#### Acceptance Criteria

- [ ] `is_precondition` returns `True` for `ConditionalRequestConflict` and `409`, in addition to today's `PreconditionFailed`/`412`.
- [ ] A `reserve` that loses a simultaneous create reaches `_resolve_reserve_collision` rather than failing hard. Asserted by test.
- [ ] `cache.cas_mutate` retries on a 409 rather than re-raising. Asserted by test.
- [ ] The existing 412 replay path (`registry.py:139-140` → `"replay"`) is unchanged — note this is the *sequential* duplicate and already worked; 409 covers only genuinely concurrent writes.
- [ ] The predicate is fixed **in place**. Consolidation is SPEC-156.

### FR-006: Every DDL literal goes through `literal()`

#### Description

`cpcommon/ddl.py:323` renders `TBLPROPERTIES` as `", ".join(f"'{k}'='{v}'" …)` and `:320` renders `LOCATION '{location}'`, both raw, while `literal()` sits at `:110` and is already used for column comments. Demonstrated: a partition enum value of `eu','projection.enabled'='false` renders as `'projection.region.values'='eu','projection.enabled'='false'`, injecting a property that turns partition projection off. Server validation checks only that `values` is a non-empty list. Blast radius is **self-scoped** — a user can only affect a table in their own database, and Athena rejects multi-statement DDL — so this is robustness, not cross-tenant escalation. The sharper path is data-quality, where the values come from **S3 key segments** (`dq_inspect_source.py:449-463`), so a folder named `year=2024'` breaks the temp-table DDL and the check dies as `query_failed`.

#### Acceptance Criteria

- [ ] Every `TBLPROPERTIES` key and value, and the `LOCATION` value, are rendered through `literal()`.
- [ ] A partition enum value containing `'` produces DDL with exactly the intended property set — no injected property. Asserted by a test that renders the statement and parses or matches the property list.
- [ ] A `LOCATION` containing `'` produces a correctly escaped single literal.
- [ ] A data-quality check over a folder whose partition segment contains `'` completes rather than failing `query_failed`. Asserted by test.
- [ ] `_projection_props` asserts that enum values are `str`, raising a validation error rather than emitting a `TypeError` from `",".join`.
- [ ] Existing rendered DDL for values with no special characters is **byte-identical** to today, so the golden-DDL tests pass unchanged.

### FR-007: Partition-key validation is complete

#### Description

`validate_authorize.py:117-124` validates `range` for `date` but never `format`; `ddl.py:180` then does `key["format"]` unguarded, so a request missing it raises a bare `KeyError` inside `infer-schema`, notified to the user as "something went wrong". The same shape applies to a non-string element in a `string` key's `values`. Separately, the browser's type declares `intervalUnit` (`tableBuild.types.ts:13`) while the renderer reads `key["interval.unit"]` (`ddl.py:183`) and `validate_authorize` mentions neither — currently **latent**, because no UI path populates it, but a trap for the next change and already documented at `load_table_definition.py:131`.

#### Acceptance Criteria

- [ ] `_validate_partition_keys` requires a non-empty string `format` for a `date` key, raising `invalid_partition_keys` naming the key.
- [ ] It validates element types: `range` entries, `values` entries, and `digits` where present.
- [ ] Every one of these refusals reaches the user as a partition-key validation message, never "something went wrong". Asserted by test per case.
- [ ] `intervalUnit` is normalised to `interval.unit` at the validation boundary (or `_projection_props` accepts both keys), so the browser's declared field cannot be silently dropped.
- [ ] A test pins that a `date` key carrying `interval` and `intervalUnit` renders both projection properties.
- [ ] The existing accepted asymmetry — `allowRemovals: false` on a create is accepted while `true` is refused (`validate_authorize.py:80`) — gains a one-line assertion recording it, since it is currently unpinned.

### FR-008: Glue read paths classify Glue's transient codes

#### Description

`apply_refresh.py:86-95` adds `InternalServiceException`/`OperationTimeoutException` — "Glue's most routine transient" — and scopes the decision in its own comment: handled locally "because that set is shared by every control plane, and this is the only Glue WRITE in the repo". That reasoning is sound for the write. The residue is that the **read** paths (`check_table_absent.py:68-74`, `load_table_definition.py:61-63`, `teardown.py:63-88`, `create_space.py:67-73`) still turn a routine Glue hiccup into a permanently failed request, and `tscommon/glue.py:23-55` has the opposite bias — every non-`EntityNotFound`/`AccessDenied` fault becomes `TransientError`, so a deterministic fault burns all retries.

#### Acceptance Criteria

- [ ] The two Glue transient codes are classified as transient on the Glue **read** paths listed above, so the state machine's existing Retry can absorb them.
- [ ] `apply_refresh`'s local handling is either replaced by the shared classifier or left in place with its comment updated to say the gap it named is now closed. Either is acceptable; silently leaving a stale comment is not.
- [ ] `tscommon.glue`'s catch-all no longer classifies a deterministic fault (e.g. `InvalidInputException`) as transient. Asserted by test.
- [ ] A test asserts the classification per code rather than asserting a count.

### FR-009: Two hygiene fixes

#### Acceptance Criteria

- [ ] `cpcommon/clients.py:77-84` `jwks(url)` keys its cache on `url` (`_jwks: dict[str, PyJWKClient]`) rather than caching the first client and ignoring the argument thereafter. Asserted by a test calling it with two URLs.
- [ ] `add_members.py` computes `normalize_members(members, owner)` **once** and reuses it for both the iteration at `:48` and the count at `:97`.
- [ ] Neither change alters observable behaviour for the single-URL, single-call case.

---

## Implementation Phases

### Phase 1: Data-quality single-file targeting

- FR-001 and FR-002 together — they interact (FR-002's sibling match is what makes FR-001's parent-promotion misfire).
- Resolve the `"$path"` form question and record the answer.

### Phase 2: Shared-space integrity

- FR-003 (teardown errors, plus the minimum fake extension it needs).
- FR-004 (`save_members` delta and the status revert).
- FR-005 (`casio` 409).

### Phase 3: Catalog DDL and request validation

- FR-006 (`literal()` for `TBLPROPERTIES` and `LOCATION`).
- FR-007 (partition-key validation, `intervalUnit` normalisation).

### Phase 4: Transient classification and hygiene

- FR-008, FR-009.

### Phase 5: Live verification

Unit tests cannot settle FR-001/FR-002 — the defect is in what Athena does with a `LOCATION` and what S3 does with a prefix. From the UI:

- Run a check on a **single file** in a folder containing several; confirm every figure describes that file and `rowCount == sum(rowCountsByFile)`.
- Place `data.csv` and `data.csv.gz` side by side; run a check on `data.csv`; confirm the manifest holds one key and the verdict reflects real data, not `clean`/`rowCount: 0`.
- Run a **folder** check and confirm the numbers match the pre-change run.
- Discharge SPEC-142's owed run in the same sitting if the `"$path"` form is confirmed — it rests on the same assumption.

### Phase 6: Completion

- Completion ritual per `CLAUDE.md`. FR-003 meets an existing SPEC-054 criterion and FR-006 changes a rendering rule — both warrant a `decisions/` entry; the rest are bug fixes and do not.
- Prune the `## Specs` note in `CLAUDE.md` of anything this spec makes stale.
