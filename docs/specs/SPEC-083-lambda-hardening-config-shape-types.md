# Spec: Lambda Hardening — Config Init-Validation, Event-Shape Validation, Type Hints

**ID:** SPEC-083
**Status:** Draft
**Last Updated:** 2026-07-02
**Depends On:** None (touches existing Lambda groups; no infra/IAM change)

## Overview

A best-practices audit of the table-builder and shared-space Lambda groups against
`docs/best-practices/lambdas/lambdas.md` and `docs/best-practices/python/python.md` found three
consistent, low-risk gaps that are cross-cutting rather than per-file. None is a live security or
correctness bug today, but each removes a class of latent failure and brings the code in line with
the rulebooks. They are grouped here because they share the same files, the same "harden the
existing functions without changing behavior on the happy path" character, and add **no** AWS
resources, IAM, or infra. Each is an independent FR that can be built and reviewed as its own phase.

## Scope

### In Scope

- **Config init-validation** in `lambdas/table-builder-common/tbcommon/config.py` and
  `lambdas/shared-space-common/config.py` (lambdas.md §6).
- **Event-shape validation** in the table-builder verb handlers that index `event[...]` directly
  (`table-builder-check-table-absent`, `table-builder-inspect-source`, `table-builder-infer-schema`)
  so a malformed/replayed task input becomes a typed terminal + actor notification, not a bare
  `KeyError` (lambdas.md §2/§9).
- **Type hints on public signatures** across `tbcommon/`, `shared-space-common/`, and the
  table-builder handlers (python.md §8, lambdas.md §13).

### Out of Scope

- Any change to the happy-path behavior, event/registry schemas, Step Function topology, or IAM.
- Adding `mypy` to CI as a gate — optional stretch noted below, not required by this spec.
- Refactoring the fat `validate_authorize` handler (tracked separately if pursued).
- The shared-space registry concurrency fix (SPEC-082).

---

## Functional Requirements

### FR-001: Required config validated at import

#### Description:

Both `config.py` modules currently read every env var with `os.environ.get(name, "")` and never
check it. Distinguish **required** vars (e.g. `USER_POOL_ID`, `APP_CLIENT_ID`, `ADMIN_BUCKET`,
`ATHENA_WORKGROUP`, `PORTAL_ROLE_ARN`, and each module's equivalents) from **genuinely optional**
ones (e.g. `NOTIFICATIONS_QUEUE_URL`, which must keep degrading gracefully per SPEC-061), and fail
fast at module import if a required var is missing or empty, with an error that names the missing
var.

#### Acceptance Criteria:

- [ ] Importing a module with a required env var unset/empty raises immediately with a message that
      names the specific variable (not a later opaque S3/JWKS error mid-invocation).
- [ ] Optional vars remain optional: absent `NOTIFICATIONS_QUEUE_URL` still results in a no-op
      notify path, not an import failure.
- [ ] The required-vs-optional split is covered by unit tests (monkeypatch env, assert raise/no-raise).
- [ ] No hardcoded ARNs/buckets/account ids are introduced; values still come from the environment.

### FR-002: Table-builder handlers validate event shape → typed terminal

#### Description:

The handlers that index required keys directly — `event["space"]["database"]`, `event["tableName"]`,
`event["format"]`, `event["sampleObjectKey"]`, etc. — must validate presence/type before use and
raise `TerminalError` (with a specific reason) on a miss, so the Step Function `Catch` records a
meaningful failure **and** the actor is notified via the existing `emit_failure` path. A bare
`KeyError` today is caught by the SFN Catch as an opaque failure and produces no actor notification.

#### Acceptance Criteria:

- [ ] A task input missing a required key raises `TerminalError` with a specific reason string, not
      `KeyError`/`TypeError`.
- [ ] The terminal path fires the actor notification (`emit_failure`) as the other terminal paths do.
- [ ] Well-formed inputs are unaffected (happy path unchanged; no new required fields).
- [ ] Tests cover at least one missing-key case per handler and confirm the typed terminal + notify.

### FR-003: Type hints on public signatures

#### Description:

Annotate public function signatures across `tbcommon/`, `shared-space-common/`, and the
table-builder handlers (`def handler(event, context) -> …`, `verified_username(id_token: str) -> str`,
`build_create_table_ddl(...)`, the `cache.py`/`registry.py`/`membership.py` surfaces, etc.), making
the thin-handler → pure-function boundary explicit and checkable. Mutable-default-arg usage was
audited and is already clean.

#### Acceptance Criteria:

- [ ] Public functions in the in-scope modules carry parameter and return annotations.
- [ ] `ruff check lambdas/` stays green; annotations introduce no runtime behavior change.
- [ ] (Stretch, optional) `mypy` runs clean over the annotated modules locally; wiring it into CI is
      explicitly deferred and not required to close this spec.

---

## Testing Notes

- Config: `monkeypatch.delenv` / `setenv` around a fresh module import (`importlib.reload`) to assert
  the fail-fast on required vars and the graceful path on optional ones.
- Event shape: feed each handler a dict missing one required key; assert `TerminalError` + that the
  notify helper was invoked.
- Keep every new test co-located with its function and green before opening the PR.

## Implementation Phases

### Phase 1: Config init-validation (FR-001)

- Add a required/optional split + validation to both `config.py`; tests.

### Phase 2: Event-shape validation (FR-002)

- Add shape checks raising `TerminalError` to the three handlers; wire `emit_failure`; tests.

### Phase 3: Type hints (FR-003)

- Annotate public signatures group by group; keep `ruff` green; optional local `mypy` pass.
