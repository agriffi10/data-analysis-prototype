# Completed Spec — SPEC-082: Shared-Space Registry Write Concurrency (optimistic CAS)

## What was completed?

The shared-space **registry** writers now use the same optimistic compare-and-swap the `cache.py` sibling
already had, so two verbs racing on one space can no longer lost-update the members list or regress a
`deleting`/terminal status back to a live one. Code-only; no AWS resources, IAM, or infra.

- **Shared CAS primitive (FR-003):** new `lambdas/shared-space-common/casio.py` — `error_code`,
  `is_precondition`, and `cas_mutate(read, apply, write)` (read+ETag → apply to the *freshly-read* value →
  conditional `PutObject`; retry on 412; exhaustion raises a typed `RuntimeError`). Both `cache._mutate` and the
  registry mutators now delegate to it, so their precondition/retry semantics can't drift. Each module keeps its
  own absent-detection (registry treats only `NoSuchKey`/404 as absent; the cache also reads a missing-key `403`
  as absent — documented on both sides).
- **Registry mutators → CAS (FR-001):** `registry.finalize`/`save_members`/`set_status` now read the record with
  its ETag via new `_read`, apply their change to the fresh record, and write via new `_put` (`If-Match`, or
  `If-None-Match: *` when absent). Happy-path output is byte-identical (no contention → fresh == the loaded
  record).
- **`reserve` failed-retry is conditional (FR-002):** the owner's "retry my own failed create" branch is now a
  bounded conditional loop (`_resolve_reserve_collision`) — the overwrite is `If-Match` on the read ETag, so two
  simultaneous retries can't both commit; the genuine first-create path (`If-None-Match: *`) is unchanged.
- **Layer packaging:** `casio` added to the `deploy-lambdas.yml` shared-space-common module list.

## What changed from earlier specs?

`cache.py` lost its private `_error_code`/`_is_precondition`/`_MAX_CAS_ATTEMPTS` (now in `casio`); its public API
is unchanged. `registry.load` is now a thin wrapper over `_read`. No signature changes to any registry mutator, so
the verb Lambdas (`add-members`/`remove-members`/`leave`/`delete`/`create`) call them exactly as before.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` **242 passed**. New tests: registry set_status/save_members CAS
preserving a concurrent writer's change (no lost update), exhaustion → `RuntimeError`, the `reserve` failed-retry
conditional under a simultaneous sibling retry, and standalone `casio` unit tests (precondition detection, re-apply
on 412, no-op skip, exhaustion, non-precondition propagation). Layer publish + live control-plane behavior deferred
to deploy (CI publishes the layer; runtime races aren't reproducible locally).
