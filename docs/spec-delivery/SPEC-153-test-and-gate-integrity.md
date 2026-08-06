# Completed Spec — SPEC-153: Test & Gate Integrity — Closing the Guards That Pass by Coincidence

## What was completed?

Ten guards that reported success without exercising the thing they existed to guard. Each now fails
when the thing it guards is broken, which is the only property that makes a guard worth having.

- **FR-001 — the layer copy list is asserted against the layer directory.**
  `test_deploy_matrix.py` gained `test_the_layer_copy_list_matches_the_layer_directory`: it parses
  the `for m in …` loop out of `deploy-lambdas.yml`'s layer job and asserts **set equality** with the
  production modules in `lambdas/shared-space-common/`. Verified negatively — adding a file to the
  directory fails the test and names it. `shared-space-common` is the repo's **only** layer built by
  an explicit file list (every other copies a whole package directory or pip-installs, so a new
  module ships automatically); `test_no_unchecked_explicit_copy_list_was_added` fails if a second
  one appears. `LAYER_PACKAGES` was corrected to all nine flat modules, with a comment stating that
  the correction is for accuracy and the **copy-list** check — not the flag map — is what closes
  SPEC-137's shape. **Consolidation:** SPEC-152 had shipped the shared-space half of this assertion in
  `test_notify_failure_import_safety.py`, which the spec (written before 152 merged) did not know. The
  duplicate was removed and its references repointed, rather than leaving two copies of one
  set-equality to drift — the packaging harness is the stated home for "how a Lambda is packaged".
- **FR-002 — the fakes paginate, and the continuation branches execute.** `FakeS3.list_objects_v2`
  honours `ContinuationToken` (a **start-after marker**, not an offset, because `delete_shared_prefix`
  deletes each page before requesting the next) and `FakeGlue.get_tables` honours `NextToken`; both
  default to a page size of **2**, so ordinary fixtures paginate. Three new tests: a multi-page
  prefix delete, a first-page denial across a shrinking prefix, and a 250-table database asserting
  `[100, 100, 50]` batches. Verified against coverage, not by eye — `teardown.py` went from three
  never-executed continuation lines to **93%**, the remaining four being the best-effort LF revoke
  and the already-absent `delete_database` path.
- **FR-003 — the intrinsic scan covers every field that evaluates intrinsics.** `_INTRINSIC_FIELDS`
  now names `Parameters`, `ResultSelector`, `ItemSelector`, `Assign`, `Output`, `Arguments`; the walk
  moved into `_throwing_intrinsics()` and the docstring was corrected (the *field* list was the narrow
  one, not the state-type list). Two synthetic fixtures guard the guard — a `States.StringToJson` in a
  `ResultSelector` is detected, and a clean `ItemSelector` is not flagged. No production machine
  changed; all four still pass.
- **FR-004 — `conftest` restores every shared-layer module.** The five hand-listed `cpcommon` modules
  became a **prefix match** over `cpcommon`/`tbcommon`/`tscommon`/`dqcommon` plus shared-space-common's
  flat modules, read from `sys.modules`. A new module in an existing layer is covered the day it is
  written. Removed as redundant: both `_PATCHED` workarounds (copy-objects and inspect-source), the
  five hand-rolled `observability.info` `try/finally` blocks, and the justification for
  `test_table_share_create_table.py`'s unrestored patch. `log_foundry` is deliberately **excluded** —
  vendored, and already save-and-restored by the `captured_events` fixture.
- **FR-005 — the notifications batch-size coupling is pinned on both sides.** `notifications_writer.handler`
  **raises** on a multi-record event instead of taking `records[0]` and discarding the rest; a test
  asserts nothing is partially written. Two infra-reading tests pin `batch_size = 1` in
  `notifications/lambda.tf` and sweep every module for a second event-source mapping or a batching
  Pipe. The four `batch_size = 1` values under `*/pipe.tf` are EventBridge Pipes targeting state
  machines — no handler assumes a single record there, and the sweep guards that scope claim rather
  than trusting it.
- **FR-006 — the two corroborated-not-discharged premises carry tripwires.**
  `test_ACCEPTED_a_mixed_case_live_table_is_silently_re_cased_on_refresh` pins that a live `Order_ID`
  becomes `order_id` on refresh while the carried comment survives.
  `test_a_table_this_pipeline_did_not_write_is_reconstructed` reconstructs a **foreign** projection
  fixture, guarded by `test_the_foreign_fixture_is_not_the_renderers_own_output`. The self-referential
  round-trip was **kept and renamed** to
  `test_the_parser_is_a_left_inverse_of_the_renderer_on_the_renderers_own_output`, which is what it
  proves. Both tripwires are cross-referenced from `decisions.md`.
- **FR-007 — broad exception assertions name what they expect.** `pre-signup`'s `_raises` helper now
  **requires** `match=` (every call site already passed one) and the bare `pytest.raises(Exception)`
  became `_raises("temporary email")` — the assertion that would have caught SPEC-137's nine-day
  `ModuleNotFoundError` in this exact handler. The two remaining broad sites are negative type
  assertions and gained `match="InvalidInputException"`. `test_copy_prefix_bounds_concurrency` now
  **observes** the bound: the fake records peak in-flight copies and the test asserts both
  `peak <= 2` and `peak == 2` (a serial loop satisfies the bound alone). New `lambdas/test_suite_hygiene.py`
  sweeps the whole fleet for `pytest.raises(Exception)` with no `match=`.
- **FR-008 — a scan that produced no report cannot read as zero findings.** ZAP's Summarize step now
  **fails the job** with a message distinguishing "the scan ran but produced no readable JSON report"
  from "found nothing", in every gate mode. `summary-section.sh` renders a non-numeric count as a
  warning rather than "No findings.", and Apply gate's default became the sentinel `no-report` so a
  missing count hard-errors instead of printing "no findings". The deliberate no-target **skip** path
  and the five hard-failing scanners are untouched.
- **FR-009 — mypy runs report-only over the shared layers.** Version-bounded `mypy>=2.3,<2.4`,
  configured in `pyproject.toml` with **every flag named**, including ones that match today's default,
  for the reason the ruff block states. Scope is the five shared layers; suites, `conftest.py` and
  `fakes.py` are excluded. Missing-stub overrides are **per module**, never blanket. CI step is
  `continue-on-error: true`.
- **FR-010 — redelivery and CAS-failure behaviour are asserted.**
  `test_ACCEPTED_a_redelivered_create_writes_a_SECOND_inbox_entry` states today's behaviour and why it
  is accepted. `test_index_store_dqcommon.py` gained the log-sweep twin's read-failure test
  (a throttled `get_object` must not truncate a space's index) and
  `test_ACCEPTED_the_cap_evicts_by_position_so_a_replay_can_outlive_a_newer_run`.

**1958 tests pass** (up from 1946), coverage **96.09%** against the 95 floor, ruff clean.

## Numbers the next notch has to beat

| Gate | Baseline at completion |
|---|---|
| mypy, shared layers, report-only | **21 findings in 12 files** (48 source files checked) |
| — by category | 9 `no-any-return`, 6 `union-attr`, 5 `arg-type`, 1 `var-annotated` |
| — by layer | cpcommon 9, tbcommon 4, tscommon 5, dqcommon 1, shared-space-common 2 |

None was investigated or fixed: FR-009 forbids changing production code to satisfy mypy in this spec.
The ratchet path — clear the baseline → flip to blocking → widen to the verb packages → `disallow_untyped_defs`
on `cpcommon` — is recorded in the `[tool.mypy]` block itself.

## Decisions taken during the build

**FR-005's multi-record outcome: raise, not loop.** The spec permitted either, forbidding only a
silent drop. Raising is loud, lands the batch in the DLQ where SPEC-126's drain turns it into a user
notification, and keeps the single-writer model's per-user serialisation a change made on purpose
rather than absorbed quietly.

**FR-010's redelivery outcome: accepted by design.** A redelivered create writes a second inbox row.
The blast radius is one duplicated line in a read-only list — no access granted, nothing overwritten,
dismissible — while the fix with real teeth is a producer-supplied idempotency key, a contract change
across four control planes and the browser producer. A cheaper remedy exists and is recorded as a
follow-up rather than taken here: deriving the notification `id` from the SQS record's `messageId`
would make a redelivery replace rather than duplicate, with no producer changes.

## What is still owed

**FR-006 AC2 was met in substance, not in letter, and this is recorded rather than discharged.** The
acceptance criterion asks for a **verbatim paste of a real `GetTable` response** for a hand-created
partition-projected table. Lake Formation filters this repo's local CLI principal's catalog to empty
(`aws glue get-databases` returns `[]`), and hand-creating a table in the account from a laptop is a
production mutation. What shipped instead is `_FOREIGN_PARAMETERS`, transcribed from AWS's published
partition-projection reference (read 2026-08-06) and surrounded by the non-projection TBLPROPERTIES
Athena and the Glue crawler stamp — provenance recorded in the file. It buys the property that
mattered (the fixture is **not** the renderer's own image) and a guard test fails if it ever becomes
so. **The verbatim capture is now an owed live check**, and the natural place to take it is the
refresh arc's owed `GetTable` read-back, which is already scheduled against a real table.

**FR-004's randomised-order requirement** was discharged by two manual full runs — a shuffled order
(seed 20260806) and a reversed order — both green (taken before the FR-001 consolidation, at 1959 tests). The repo has no ordering plugin and
this spec did not add one.

## Files

| Path | What changed |
|---|---|
| `lambdas/test_deploy_matrix.py` | FR-001 copy-list equality, guard-the-guard, `LAYER_PACKAGES` correction |
| `lambdas/test_suite_hygiene.py` | **new** — repo-wide sweep for match-less `pytest.raises(Exception)` |
| `lambdas/conftest.py` | FR-004 prefix-matched shared-layer snapshot |
| `lambdas/shared-space-common/fakes.py` | FR-002 paginating `list_objects_v2` / `get_tables` |
| `lambdas/notifications-writer/notifications_writer.py` | FR-005 raise on a multi-record event |
| `.github/workflows/security.yml`, `.github/scripts/summary-section.sh` | FR-008 empty-report path |
| `.github/workflows/ci.yml`, `pyproject.toml`, `lambdas/requirements-dev.txt` | FR-009 mypy, report-only |

Plus test-only changes in `test_state_machines_cpcommon.py`, `test_index_store_dqcommon.py`,
`test_notifications_writer.py`, `test_common.py`, `test_apply_refresh.py`, `test_load_table_definition.py`,
`test_pre_signup.py`, `test_create_space.py`, and the four files whose local restore workarounds were
removed.

## Component inventory / help

**No new reusable service, hook or component** — every addition is a test, a fixture capability or a
CI/config change, so no inventory row is owed. **Nothing user-facing changed**: the notifications
writer's new raise is reachable only if the Terraform `batch_size` is edited, which the same spec now
forbids by test, so no Help & guides update is owed either.
