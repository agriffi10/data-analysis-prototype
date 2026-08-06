# Completed Spec — SPEC-151: Control-Plane Correctness — Single-File Checks, Teardown Integrity & DDL Escaping

## What was completed?

Nine correctness defects across the Python control planes, all sharing one shape: **a guard or a
helper exists, and one call site does not use it.** Python only — `infra/` and `apps/portal/`
untouched, as the spec required.

- **FR-001/002 — a single-file check now describes the selected file.** `sql.single_file_path` is the
  one definition of "targets one file"; `_only_selected` filters the listing to the exact key; the
  `"$path"` predicate narrows the profile, duplicates **and** ragged queries.
- **FR-003 — teardown surfaces per-key failures.** `teardown.TeardownIncompleteError`, raised from
  `delete_shared_prefix` and `drop_database`, so a partial teardown no longer frees the name.
- **FR-004 — `save_members` takes a delta** (`add` / `remove` / `acknowledge`) applied inside the CAS,
  and returns the committed record.
- **FR-005 — `casio.is_precondition`** recognises the racing 409.
- **FR-006 — `literal()` on `TBLPROPERTIES` and `LOCATION`**, plus a string assertion in
  `_projection_props`.
- **FR-007 — partition-key validation completed**; `intervalUnit` accepted alongside `interval.unit`.
- **FR-008 — Glue's two routine transients** added to `cpcommon.errors._TRANSIENT_CODES`;
  `tscommon.glue`'s catch-all now classifies instead of assuming.
- **FR-009 — `clients.jwks(url)` keyed by URL**; `normalize_members` computed once.

### The two defects that reached users

A check on **one file** silently profiled its whole parent folder, because an Athena `LOCATION` is
read recursively — so `rowCount`, `duplicateRows` and every per-column figure described the folder
while `rowCountsByFile` described the one file. Worse, the listing prefix was a *prefix* match, so a
check on `data.csv` also matched `data.csv.gz`; when it did, `keys == [prefix]` went false, the
parent-promotion did not apply, the table was built over an empty path, `GROUPING SETS` still emitted
a total row so `MissingProfileError` never fired, and the user got **`verdict: "clean"`,
`rowCount: 0`** over data nothing had read.

A **partial teardown freed the space name**: `delete_objects` and `batch_delete_table` both return
HTTP 200 with a per-item `Errors` array, both return values were discarded, and `delete_space` then
ran `reg.delete(space)` — commented "LAST — the name is now free to reuse".

### Deliberate deviations

- **All THREE query builders are narrowed, not the two FR-001's description names.** `duplicateRows`
  is in FR-001's own list of figures that must describe the selected file, and ragged's `total_lines`
  counted every line in the folder — so a single-file check reported its ragged count against a
  denominator describing the neighbours.
- **FR-002's "no clean verdict from an empty profile" is a FINDING, not a raise** (user decision). A
  header-only CSV — which `report.py` itself calls "a failed export, one of the commoner real
  defects" — profiles to exactly this and is a real result the user needs delivered. Raising would
  make a data defect indistinguishable from an infrastructure fault; the false-clean is closed either
  way, because the verdict is no longer `clean`.
- **FR-004 has FOUR callers, not the three the FR lists.** `acknowledge-membership` also calls
  `save_members` and is the only one that *adds* to `acknowledged`; left out it would have kept
  passing a computed list and kept the defect. `acknowledged` carried the identical stale-snapshot
  bug, so it is derived in the CAS too.
- **FR-004's callers now fan the roster out from the COMMITTED record**, where the FR says the fan-out
  is "unchanged". Fanning out from the caller's own list would put the same stale-read defect one
  layer down, with the cache disagreeing with the registry. Behaviour is unchanged uncontended.
- **`save_members` no longer sets `status`** at all beyond a `setdefault` — it used to force
  `"active"`, so a membership write racing a delete returned a `deleting` space to `active` and the
  cascade then ran against a record claiming to be healthy.
- **FR-008 was fixed in the SHARED classifier**, not per-verb. `_TRANSIENT_CODES` missed Glue's two
  most routine faults *by a word* (`InternalServerException` vs Glue's `InternalServiceException`).
  Widening is safe — only Glue and Lake Formation raise them, and both are retryable there.
  `apply_refresh` keeps its local set (it matches directly, not via the classifier) with its comment
  updated to record that the gap it named is closed.

## What changed from earlier specs?

- **SPEC-054's teardown acceptance criterion is finally met** — "never a dangling … half-deleted
  resource". Both `delete-space` and `forget-space` inherit it, sharing the helpers.
- **`save_members` signature changed** (SPEC-082/073/075 path): now `save_members(registry,
  request_id, *, add=(), remove=(), acknowledge=())`, returning the committed record.
- **`build_profile_query` / `build_duplicates_query` / `build_ragged_query`** each gained an optional
  trailing `path_filter`; `dq_inspect_source._resolve_listing_prefix` now returns
  `(prefix, is_single_file)`.
- **SPEC-110's stale docstring corrected** — the claim that a parent-folder location "is still
  correct here because the manifest listed exactly that one object" was the load-bearing wrong
  belief. `effective_acknowledged`'s docstring lost the persist-before-`save_members` contract FR-004
  deleted.
- **`fakes.py` gained `undeletable` / `undroppable`** — the minimum needed to express a partial AWS
  failure. Deeper fake work stays SPEC-153's.

## Verification

`pytest lambdas/` **1844 passed**, 95.92% (gate 95); `ruff check lambdas/` clean. Every fix verified
by **counterfactual** — reverting each and confirming the new tests go red (3 for FR-002, 5 for
FR-003, 4 for FR-004, 4 for FR-005, 3 for FR-006, 5 for FR-007, 6 for FR-008). One of those runs
caught FR-001's *wiring* being untested when only the builders were covered.

**Phase 5 discharged (2026-08-05), from the UI.** A single-file check in a populated folder reported
that file's rows and not the folder's; `data.csv` beside `data.csv.gz` manifested one key and
returned real data rather than `clean`/`rowCount: 0`; a folder check was unchanged; a header-only
source reported the new finding instead of `clean`. A shared-space delete completed cleanly, covering
FR-003's success direction.

### Still owed, and deliberately not claimed as done

- **FR-006's engine-level proof.** The escaping is asserted at *render* time. A data-quality check
  over a folder whose partition segment contains `'` was not run, so that Athena accepts the escaped
  form is corroborated, not demonstrated.
- **FR-003's failure direction.** Only a successful teardown was exercised; a denied key cannot be
  staged easily from the UI.
- **SPEC-142's own scenario is NOT discharged.** Phase 5 confirmed the `"$path"` form the ragged
  mapping depends on — the single-file predicate demonstrably matched — but the disagreeing-files
  case (cross-file finding, no ragged count) was never run. See `CLAUDE.md`.
