# Spec: Test & Gate Integrity — Closing the Guards That Pass by Coincidence

**ID:** SPEC-153
**Status:** Completed
**Last Updated:** 2026-08-05
**Depends On:** SPEC-137 (its post-mortem is this spec's subject — the code/infra split whose gates were all blind), SPEC-138 (the scanner gates and the "did not run is never clean" rule), SPEC-125 (`shared-space-common` and the fakes FR-002 deepens), SPEC-149 (the case-folding premise FR-006 pins), SPEC-143 (the projection reconstruction FR-006 pins)

> **Reference:** from the 2026-08-05 codebase audit. This spec is about the tests that exist to catch a class of failure and cannot.
>
> **The theme is guards passing by coincidence.** `test_deploy_matrix.py` was written *because* SPEC-137 shipped instrumented code whose layer attachment was missing and every gate was blind to it — yet it never checks the layer job's copy list against the layer directory, which is the actual failure shape. The fleet's fakes accept a `ContinuationToken` and ignore it, so three continuation branches have never executed. The intrinsic scanner walks one ASL field while its docstring claims every state type. A suite patches a module and never restores it, in a `conftest` whose snapshot covers only five of nine shared modules.
>
> **Two of these are honest-uncertainty markers, not bugs.** FR-006 adds `ACCEPTED_`-prefixed tripwire tests for the two premises the repo has correctly identified as corroborated-not-discharged: Athena's column-name fold, and the self-referential projection fixture. The repo already invented this idiom (`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`); this applies it where it is owed. **A tripwire that starts failing is a signal to revisit the decision, not to delete the test** — each one says so in its docstring.
>
> **What this spec does not do is add coverage for its own sake.** Every item closes a specific, named blind spot. Frontend journey coverage is SPEC-154.

## Overview

This codebase takes testing seriously and it shows: 1745 Lambda tests at 96% coverage, fakes that implement real semantics rather than returning canned dicts, and several meta-tests that read deployed Terraform and ASL as data. The audit found almost none of the usual anti-patterns — no tautologies, no `assert mock.called`, no vacuous assertions.

What it found instead is subtler and more dangerous: a handful of guards that report success without exercising the thing they exist to guard. The most consequential is the deploy-matrix test. It was written in direct response to SPEC-137 — nine days of `ModuleNotFoundError` at cold start because a layer attachment shipped in code but not in infra — and it checks that each function's imports have a matching matrix flag. It does not check that the layer *zip* actually contains the modules the layer directory holds. Add a module, import it from a function whose row already says `layer: true`, and the matrix test passes, the deploy goes green, and the function fails at cold start. That is SPEC-137 again, through the gate built to stop it.

The rest are the same shape at smaller scale: pagination branches that no fake can reach, an intrinsic scanner with four unscanned fields, an unrestored module patch that the neighbouring suite already worked around locally, and a scanner gate that passes a zero finding count through when the scan produced no report at all.

The outcome is that each of these guards fails when the thing it guards is broken — which is the only property that makes a guard worth having.

---

## Scope

### In Scope

- **A layer-contents assertion**: the layer job's copy list is checked against the layer directory.
- **Pagination-capable fakes**, and tests that drive the continuation branches.
- **A complete intrinsic scan** across every ASL field that evaluates intrinsics.
- **A `conftest` module snapshot** covering all shared layers, and removal of the local workarounds it makes redundant.
- **A pinned code/infra coupling** for the notifications event-source-mapping batch size.
- **CAS parity** between `dqcommon.index_store` and its `log-sweep` twin.
- **`ACCEPTED_` tripwires** for the Athena case-fold premise and the self-referential projection fixture.
- **`match=` on broad `pytest.raises`**, starting with the `pre-signup` handler.
- **A scanner-gate fix** so an empty report cannot read as zero findings.
- **mypy, report-only, over the shared layers** — the ratchet's first notch.

### Out of Scope

- **Frontend test work of any kind** — SPEC-154.
- **Fixing the bugs these tests would catch.** FR-002's fakes will make SPEC-151 FR-003's teardown fix fully testable, but the fix itself belongs to SPEC-151 and must not wait on this spec. If SPEC-151 lands first, FR-002 deepens its tests rather than replacing them.
- **Raising coverage thresholds.** SPEC-150 FR-002 sets them at the measured level; this spec may raise coverage as a side effect but does not move the floors.
- **`noUncheckedIndexedAccess`.** Named as a follow-up ratchet; 239 sites and two load-bearing cases make it its own decision.
- **Making mypy blocking.** Report-only is the whole of FR-009.
- **Rewriting the ZAP scan or changing its target policy.** FR-008 fixes one gate-input path and nothing else — the skip-loudly-rather-than-default behaviour is a written decision (`security.yml:605-606`) and stays.

---

## Functional Requirements

### FR-001: The layer zip is asserted to contain what the layer directory holds

#### Description

`deploy-lambdas.yml:71-73` publishes eight flat modules from `shared-space-common` via `for m in config casio auth registry membership cache notify teardown`. Nothing anywhere checks that list against the directory. `test_deploy_matrix.py:37-44`'s `LAYER_PACKAGES` maps only four of them and `:157` silently `continue`s past the rest — but note that mapping the missing four would **not** close this hole, because all eight ship in one layer behind one flag. The missing assertion is about the copy list, not the flag map.

#### Acceptance Criteria

- [ ] A test parses the module list out of `deploy-lambdas.yml`'s layer job and asserts **set equality** with the Python modules present in `lambdas/shared-space-common/` (excluding `test_*.py`, `conftest.py`, `fakes.py`).
- [ ] Adding a module to the directory without adding it to the workflow list **fails** the test. Verified by temporarily adding a file, observing the failure, then removing it.
- [ ] The same assertion covers every other layer built by an explicit file list, not only `shared-space-common`. Layers packaged wholesale (a whole package directory) are exempt with a named reason.
- [ ] The test names the missing module in its failure message.
- [ ] `LAYER_PACKAGES` is additionally corrected to include `config`, `auth`, `cache` and `notify`, with a comment recording that the correction is for accuracy and that FR-001's copy-list check — not the flag map — is what closes SPEC-137's shape.
- [ ] A guard-the-guard test asserts the derived module set is non-trivial (at least 8 entries), in the style of `test_the_matrix_was_actually_parsed`.

### FR-002: The fakes can paginate, and the continuation branches execute

#### Description

No `test_*.py` in the fleet mentions `NextToken`, `ContinuationToken` or `IsTruncated`. `fakes.py:89` accepts `ContinuationToken` and ignores it, hard-coding `IsTruncated: False`; `get_tables:120` ignores `NextToken`. So the three continuation assignments in `teardown.py:30,36,75` and the `range(0, len(tables), 100)` batching have never executed under test. (Paginators *are* driven elsewhere via `get_paginator` in four suites — this is specifically the hand-rolled continuation loops.)

#### Acceptance Criteria

- [ ] `FakeS3.list_objects_v2` honours `ContinuationToken`, returns `IsTruncated` truthfully and supplies `NextContinuationToken`, with a small configurable page size (default small enough that ordinary fixtures paginate).
- [ ] `FakeGlue.get_tables` honours `NextToken` equivalently.
- [ ] A test deletes a shared prefix spanning **more than one page** and asserts every object is gone.
- [ ] A test drops a database with **more than 100 tables** and asserts more than one `batch_delete_table` call and an empty database.
- [ ] Every continuation line in `teardown.py` is executed by the suite — verified against the coverage report, not asserted by eye.
- [ ] Existing single-page tests continue to pass unchanged.

### FR-003: The intrinsic scan covers every field that evaluates intrinsics

#### Description

`test_state_machines_cpcommon.py:111-115` iterates `state.get("Parameters")` only. ASL also evaluates intrinsics in `ResultSelector`, `ItemSelector`, `Assign` and `Output`. No current machine has an intrinsic in those fields — `table-share:72`'s `ItemSelector` contains only `$$.Map.Item.Value` and `$` — so this is a coverage hole rather than a live defect, but a `States.StringToJson` added to a `ResultSelector` would be exactly as uncatchable and entirely unscanned.

#### Acceptance Criteria

- [ ] The scan iterates `Parameters`, `ResultSelector`, `ItemSelector`, `Assign`, `Output` and `Arguments`, reusing the existing `_intrinsics_in` recursion.
- [ ] A test fixture containing a throwing intrinsic in a `ResultSelector` is detected. The fixture is synthetic; no production machine is modified.
- [ ] The docstring is corrected so its claim matches what the code walks.
- [ ] All four production machines still pass.

### FR-004: `conftest` restores every shared layer module

#### Description

`lambdas/conftest.py:38`'s `_SHARED_MODULES` covers five `cpcommon` modules and none of `tbcommon`, `tscommon`, `dqcommon`, `shared-space-common` or `cpcommon.observability`. `test_table_share_create_table.py:73-76` patches `m.athena_mod.run_ddl` with no restore; the neighbouring `test_table_share_copy_objects.py:73-83` hit the same problem and worked around it locally, with a comment saying tscommon "is NOT covered by conftest's module snapshot, so an unrestored stub here leaks into the copy_plan suite". Five files hand-roll `try/finally` around `observability.info`.

#### Acceptance Criteria

- [ ] `_SHARED_MODULES` covers the four domain layers and `cpcommon.observability`.
- [ ] The local workaround in `test_table_share_copy_objects.py` and the five hand-rolled `observability` `try/finally` blocks are removed, since the fixture now covers them.
- [ ] `test_table_share_create_table.py`'s unrestored patch is either removed or made redundant by the fixture.
- [ ] The full suite passes in a **randomised file order** as well as the default order, demonstrating no cross-suite leakage. If the project has no ordering plugin, a single manual shuffled run is recorded in the delivery doc instead.

### FR-005: The notifications batch-size coupling is pinned

#### Description

`notifications_writer.py:279` takes `records[0]` and discards the rest — correct only because `infra/modules/notifications/lambda.tf:75` sets `batch_size = 1`. `grep -rn batch_size lambdas/` returns **zero** hits, so nothing connects the two halves. Raising the batch size is a one-line Terraform edit that would silently drop notifications.

#### Acceptance Criteria

- [ ] A test reads `infra/modules/notifications/lambda.tf` and asserts `batch_size = 1`, in the idiom of `test_validate_authorize.py:465`, with a docstring explaining that the handler's single-record assumption depends on it.
- [ ] **Either** the handler processes every record in the batch, **or** it raises on a multi-record event rather than silently dropping. Whichever is chosen is asserted by test and recorded as the decision — silently discarding is not an acceptable outcome of this spec.
- [ ] The same coupling check is applied to any other event-source mapping whose handler assumes a single record. If none exists, that is asserted by the same test's scope comment.

### FR-006: The corroborated-not-discharged premises carry tripwires

#### Description

Two premises are load-bearing and unverified, and the repo has correctly said so in prose. **Athena's column-name fold**: SPEC-149 moved the lowercase fold into our code, so if the premise is wrong the first refresh of a mixed-case table silently re-cases every column while `diff-schema` reports "unchanged". `test_apply_refresh.py:85`'s `_live_table()` supplies already-lowercase names, so the fixture assumes the conclusion. **The projection round-trip**: `test_load_table_definition.py:326-364` builds the fixture's `Parameters` from `ddl.projection_properties` and asserts the reconstruction re-renders identically — render → parse → render, compared against render, which proves the parser is a left-inverse of the renderer on the renderer's own image and cannot see disagreement with a table created outside this pipeline.

#### Acceptance Criteria

- [ ] A test named with the repo's `test_ACCEPTED_` prefix pins today's behaviour for a **mixed-case** live table fixture (e.g. `{"Name": "Order_ID"}`), documenting in its docstring that the Athena fold is corroborated by AWS documentation but not verified here, and that a failure means the premise should be revisited — not the test deleted.
- [ ] At least one projection fixture's `Parameters` is a **verbatim paste of a real `GetTable` response** for a hand-created partition-projected table, with a comment recording where it came from and when.
- [ ] The existing self-referential round-trip test is kept and relabelled to say what it does prove, rather than being deleted or left implying more.
- [ ] Both tripwires are cross-referenced from the relevant `decisions/` entry so the link survives the test file.
- [ ] These tests do not change production behaviour.

### FR-007: Broad exception assertions name what they expect

#### Acceptance Criteria

- [ ] `pre-signup/test_pre_signup.py:119`'s `pytest.raises(Exception)` gains a `match=` naming the expected message. This is the handler whose nine-day outage was an `ImportError`, which the current assertion would accept.
- [ ] The `_raises` helper at `:20-28`, which accepts any exception when `match is None`, either requires a match or documents per call site why one is not possible.
- [ ] `test_copy_prefix_bounds_concurrency:170` either observes the bound (recording peak in-flight in the fake) or is renamed to what it actually asserts.
- [ ] A repo-wide check confirms no remaining bare `pytest.raises(Exception)` without a `match=` or a written reason.

### FR-008: A scan that produced no report cannot read as zero findings

#### Description

`security.yml:648-649` warns that it is "reporting 0, which may not mean clean" and then passes `0` to the gate anyway. Harmless under `report`; under `block` a broken scanner reads as a pass — the precise thing `decisions/` forbids with "'did not run' is never 'clean'". Note the *skip* path at `:604-611` is a deliberate written decision and is **not** in scope.

#### Acceptance Criteria

- [ ] A scanner that ran but produced no readable report fails its job regardless of gate mode, rather than passing `0` findings through.
- [ ] The failure message distinguishes "scan produced no report" from "scan found nothing".
- [ ] The deliberate no-target **skip** behaviour at `:604-611` is unchanged.
- [ ] The five hard-failing scanners are unaffected.

### FR-009: mypy runs report-only over the shared layers

#### Description

`ci.yml:76-80` runs ruff and pytest; there is no type checker for a fleet whose contract with the SPA is JSON envelope shapes. Start where a signature change fans out.

#### Acceptance Criteria

- [ ] mypy is added to `lambdas/requirements-dev.txt`, **version-pinned**, following the ruff precedent and its written reasoning about inherited defaults.
- [ ] Configuration in `pyproject.toml` selects a rule set explicitly rather than inheriting mypy's evolving defaults — the same principle the ruff block states.
- [ ] Scope is the shared layers only: `cpcommon`, `tbcommon`, `tscommon`, `dqcommon`, `shared-space-common`.
- [ ] The CI step is **report-only** (`continue-on-error` or an explicit non-blocking invocation) and says so in a comment, with the intended ratchet path recorded.
- [ ] The baseline finding count is recorded in the delivery doc so the next notch has a number to beat.
- [ ] No production code is changed to satisfy mypy in this spec. If a finding reveals a real defect, it is filed, not fixed here.

### FR-010: Redelivery and CAS-failure behaviour are asserted, not assumed

#### Description

These pipelines are at-least-once, and two of them have no test saying what a redelivery does. `notifications_writer.apply_create:172` mints `uuid.uuid4().hex` per invocation, so a redelivered SQS record produces a **second inbox entry** for one event — FIFO `MessageDeduplicationId` only covers a 5-minute producer window, and the visibility-timeout redelivery path is not bounded by it. `dqcommon/index_store.py:160` handles the equivalent case and **is** tested (`test_a_replayed_request_replaces_its_row_instead_of_duplicating_it`); the user-facing inbox has no equivalent. Separately, `index_store` is missing its twin's `test_a_read_failure_never_overwrites_an_existing_day` (`test_log_sweep.py:765`) — `_read:95` swallows **any** exception and returns `([], None)`, so "a transient read failure cannot truncate a space's index" is asserted nowhere.

#### Acceptance Criteria

- [ ] A test drives a **redelivered** notification create and asserts today's behaviour explicitly. If the outcome is a duplicate inbox entry, the test is named to say the duplication is accepted-by-design and the reasoning is recorded; if it is judged wrong, a producer-supplied dedup key is introduced and same-key-replaces is asserted. **Either outcome is acceptable; leaving the behaviour unstated is not.**
- [ ] `test_index_store_dqcommon.py` gains the twin's read-failure test: seed entries, make `get_object` raise a throttling error, assert the existing entries survive and `append` returns `False`.
- [ ] The `index_store` cap's position-based eviction gains a test recording the accepted behaviour. Note this is a **documented** choice — the comment at `:161-163` states the dashboard sorts by timestamp itself — so the test pins that a replayed old run cannot evict a newer row, or records that it can and that this is accepted.
- [ ] No production behaviour changes under this FR unless the redelivery decision above explicitly calls for it.

---

## Implementation Phases

### Phase 1: The SPEC-137 shape

- FR-001 — the layer copy-list assertion, plus the `LAYER_PACKAGES` correction and the guard-the-guard.
- This goes first because it is the highest-value item and the reason the spec exists.

### Phase 2: Fakes and the branches they unlock

- FR-002 — paginating fakes, continuation tests, coverage verification.
- Coordinate with SPEC-151 Phase 2 if it has not landed: the teardown fix and these fakes meet here.

### Phase 3: Scanner and coupling assertions

- FR-003 (intrinsic fields), FR-005 (batch-size coupling and the multi-record decision), FR-010 (redelivery behaviour and the `index_store` CAS parity tests).

### Phase 4: Suite hygiene

- FR-004 (`conftest` snapshot, removing the local workarounds), FR-007 (`match=` and the misnamed test).

### Phase 5: Tripwires

- FR-006 — the two `ACCEPTED_` tests and the real `GetTable` fixture.

### Phase 6: Gates

- FR-008 (empty-report path), FR-009 (mypy report-only).

### Phase 7: Completion

- Completion ritual per `CLAUDE.md`.
- FR-006's tripwire idiom and FR-001's copy-list rule are both worth `decisions/` entries — the first because it records what the project accepts as unverified, the second because it states what a layer gate must check.
