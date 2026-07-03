# Completed Spec — SPEC-083: Code-Quality Hardening (Lambda config/shape/types + SPA cleanups)

Shipped as **two PRs** (the Lambda half and the SPA half are independent, per the spec). No happy-path
behavior change; no infra/IAM.

## What was completed?

### Lambda half (FR-001→005)
- **FR-001:** both `config.py` modules validate **required** env vars at import via `_require` (fail fast
  naming the missing var); `NOTIFICATIONS_QUEUE_URL` / `MAX_SHARED_MEMBERSHIPS` stay optional. New
  `lambdas/conftest.py` stamps a pytest baseline; `test_config_shared_space.py` / `test_config_tbcommon.py`
  exercise the fail-fast via `importlib.reload`.
- **FR-002:** new `tbcommon.events.require` validates verb task-input shape; `check-table-absent` /
  `inspect-source` / `infer-schema` raise `TerminalError(malformed_event)` + notify the actor (new
  `malformed_event` message) instead of a bare `KeyError`.
- **FR-004:** `validate_authorize` + `check_table_absent` handlers thinned to `parse → delegate → return`
  (orchestration in a pure function).
- **FR-005:** `import jwt` hoisted to module scope in both `auth.py`; `messages.failure_message` substitutes
  placeholders via `str.replace` (no `.format` brace footgun); `registry.now_iso` via `datetime`.
- **FR-003:** parameter/return type hints on public signatures across `tbcommon/`, `shared-space-common/`,
  and the verb handlers.

### SPA half (FR-006→010)
- **FR-006:** `SelectionProvider` mutators are `useCallback`-stable over `dispatch`; `useConnections` returns a
  `useMemo`'d object with `useCallback`-stable `refresh`/`reconcile` (and a memoized query key).
- **FR-007:** `QueryWorkspace` `savedById`/`dirtyTabIds`/`activeLinkedSaved` are `useMemo`'d on their inputs
  (still derived in render, not stored in state).
- **FR-008:** `useNotifications` unmount cleanup reads the timer array's `.current` at teardown (robust to
  reassignment); `UploadQueueProvider`'s `itemsRef` sync kept as-is (already documented as intentional).
- **FR-009:** `QueryWorkspace.submit` de-dupe guard now reads a `submittingTabsRef` (Set) so a rapid
  double-trigger before `runs` commits still starts at most one execution.
- **FR-010:** `QueryResultsTable` array-index keys documented as safe (static, fully-replaced-per-page table,
  no per-cell focus/state; column names can collide).

## What changed from earlier specs?

Internal refactors only — no public component/hook/service **signature** changed (return-object identities are
now more stable). `cache.py` lost its private `_error_code`/`_is_precondition` (moved to `casio` in SPEC-082,
already merged). Adds `lambdas/conftest.py` and `tbcommon/events.py`; `casio` was already added to the
tbcommon/shared-space layer manifests (SPEC-082 for shared-space; `events` ships automatically inside the
`tbcommon` package layer).

## Verification

- Lambda: `ruff check lambdas/` clean; `pytest lambdas/` **254 passed**.
- SPA: `format:check`, `tsc`/`build`, ESLint (no `exhaustive-deps` suppression), Vitest **905 passed** (+ the
  FR-009 double-submit de-dupe test and the FR-008 unmount-timer-cleanup test).
