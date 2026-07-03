# Spec: Code-Quality Hardening — Lambda Config/Shape/Types + Lambda & SPA Cleanup

**ID:** SPEC-083
**Status:** Completed
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

The same audit also turned up a set of **lower-priority smells** — individually not worth their own
spec — spanning both the Lambdas and the SPA (React). Rather than lose them, they are folded into this
spec as additional FRs (FR-004 → FR-010) so they get completed as part of this hardening pass. They
keep the same "no behavior change on the happy path, no infra" character; the SPA items are memoization
/ effect-robustness / key cleanups, and one is a genuine de-dupe-guard robustness fix.

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
- **Lambda cleanup smells** (FR-004, FR-005): thin the fat `validate_authorize` / `check_table_absent`
  handlers; hoist in-body `import jwt`; guard the `messages.py` `.format()` footgun; `now_iso` via
  `datetime`.
- **SPA cleanup smells** (FR-006 → FR-010): stabilize unmemoized context/hook value identities,
  memoize derived structures in `QueryWorkspace`, harden effect-cleanup robustness, fix the query
  submit de-dupe guard's stale-snapshot read, and resolve array-index list keys.

### Out of Scope

- Any change to the happy-path behavior, event/registry schemas, Step Function topology, or IAM.
- Adding `mypy` to CI as a gate — optional stretch noted below, not required by this spec.
- The shared-space registry concurrency fix (SPEC-082) and the Monaco autocomplete lifecycle fix
  (SPEC-084) — their own specs.

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

### FR-004: Thin the fat handlers (delegate to pure functions)

#### Description:

`validate_authorize.py`'s `handler` runs ~45 lines of extract → parse → verify → authorize →
validate → assemble inline (including the notify-on-failure envelope), and `check_table_absent.py`'s
`handler` inlines its Glue call + notify rather than delegating like the sibling handlers
(`_inspect`/`_infer`). Move the orchestration into a delegated pure function so the handler is thin
and the logic is testable without invoking `handler` (lambdas.md §2).

#### Acceptance Criteria:

- [ ] `validate_authorize` and `check_table_absent` handlers are thin: parse → delegate → return,
      with the orchestration + notify envelope in a named function testable without a Lambda context.
- [ ] Behavior is unchanged (same outputs, same terminal/notify paths); existing tests still pass and
      logic is covered by calling the delegated function directly.

### FR-005: Lambda Python-style cleanups

#### Description:

Small `python.md`/`lambdas.md` conformance fixes surfaced by the audit, none behavior-changing on the
happy path:
- Hoist the in-function `import jwt` to module scope in `tbcommon/auth.py` and
  `shared-space-common/auth.py` — it is always needed by `verified_username`, so the lazy import buys
  nothing (python.md §4, lambdas.md §5).
- Guard `tbcommon/messages.py`'s `failure_message` `.format()` so a body string containing a literal
  `{` cannot raise `KeyError`/`ValueError` (only format when placeholders are present, or escape) —
  a latent footgun today (python.md §11).
- `shared-space-common/registry.py` `now_iso` uses `datetime.now(timezone.utc)` rather than
  `time.gmtime()`/`strftime` (python.md §13, idiomatic timestamp).

#### Acceptance Criteria:

- [ ] `import jwt` is at module scope in both `auth.py` modules; `verified_username` behavior unchanged.
- [ ] `failure_message` produces identical output for existing bodies and does not raise for a body
      containing a literal brace; covered by a unit test.
- [ ] `now_iso` returns an equivalent ISO-8601 UTC timestamp via `datetime`; existing callers/tests pass.

### FR-006: Stabilize context / hook value identities

#### Description:

Two shared values hand consumers fresh function/object references every render:
`SelectionProvider` (`selectionContext`) recreates `toggle`/`selectAll`/`clear`/`isSelected` on every
selection change instead of wrapping them in `useCallback` over the stable `dispatch`; and
`useConnections` returns a new object literal with freshly-allocated `refresh`/`reconcile` closures
each render. Memoize both so consumers relying on referential stability (e.g. a memoized child, or a
`refresh`/`reconcile` used as an effect dep) don't churn (react.md §8/§12/§15).

#### Acceptance Criteria:

- [ ] `SelectionProvider`'s exposed callbacks are `useCallback`-stable across renders that don't change
      their own deps; the context value only changes identity when the selection actually changes.
- [ ] `useConnections` returns a memoized object with `useCallback`-stable `refresh`/`reconcile`.
- [ ] No behavior change; existing tests pass and no `react-hooks/exhaustive-deps` suppression is added.

### FR-007: Memoize derived structures in `QueryWorkspace`

#### Description:

The app's heaviest component rebuilds `savedById` (a `Map`), `dirtyTabIds` (a `Set`), and
`activeLinkedSaved` on every render, and passes freshly-allocated async handlers to dialog children.
Wrap the derived structures in `useMemo` (keyed on their real inputs, e.g. `[saved.queries, tabs.tabs]`)
and the child-passed handlers in `useCallback` where it removes churn — keeping them derived in render,
not stored in state (react.md §3/§15).

#### Acceptance Criteria:

- [ ] `savedById`/`dirtyTabIds`/`activeLinkedSaved` are `useMemo`'d on their inputs (still derived, not
      stored in state).
- [ ] Handlers passed to memoizable dialog children are stabilized where it reduces re-renders.
- [ ] No behavior change; existing `QueryWorkspace` tests pass.

### FR-008: Harden effect-cleanup robustness

#### Description:

`useNotifications`'s unmount cleanup captures `reconcileTimers.current` once at mount and only works
because that array reference is never reassigned — a future `reconcileTimers.current = []` would strand
timers. Make the cleanup clear whatever timers are pending at teardown regardless of ref reassignment.
Also revisit `UploadQueueProvider`'s `itemsRef`-synced-in-effect read used by the stable `cancel`
callback: keep it if intentional (documented), or have `cancel` dispatch and let the reducer look up
the item (react.md §9/§10).

#### Acceptance Criteria:

- [ ] `useNotifications` clears all pending reconcile timers on unmount without depending on the timer
      array never being reassigned; no timer/test-timer leak.
- [ ] `UploadQueueProvider`'s latest-items read is either reducer-driven or retains a one-line comment
      stating why the ref-sync is the chosen approach; behavior unchanged.

### FR-009: Fix the query submit de-dupe guard's stale-snapshot read

#### Description:

`QueryWorkspace.submit()` computes its `inFlight` guard by reading `runs[tabId]`/`statuses[tabId]` from
the render snapshot. Because `submit` isn't memoized and reads state directly (rather than via an
updater/ref), a rapid double-trigger around a state transition (e.g. `onViewData` opens a tab and calls
`submit` in the same tick) can read a pre-commit snapshot and fail to de-dupe. Read the in-flight state
through a ref or functional update so the guard reflects the latest committed state (react.md §6).

#### Acceptance Criteria:

- [ ] The `inFlight` guard reads the latest in-flight state (via ref/updater), not a stale render
      snapshot.
- [ ] A rapid double-trigger of `submit` for the same tab starts at most one execution; covered by a test.
- [ ] The existing auto-run-with-explicit-id path continues to work.

### FR-010: Resolve array-index list keys in `QueryResultsTable`

#### Description:

`QueryResultsTable` uses array indices as `key` for `<col>`/`<th>`/`<tr>`/`<td>`. It is benign for the
current static text table, but reuses the same DOM node across Prev/Next for a different logical row —
a latent bug if a cell ever holds focus or local state (react.md §4). Use stable keys where a stable
identity exists, or document why index keys are acceptable for this render-only table.

#### Acceptance Criteria:

- [ ] List keys are stable where a stable identity is available; otherwise a one-line comment records
      why index keys are safe for this static, fully-replaced-per-page table.
- [ ] No visual/behavior change to the results table; existing tests pass.

---

## Testing Notes

- Config: `monkeypatch.delenv` / `setenv` around a fresh module import (`importlib.reload`) to assert
  the fail-fast on required vars and the graceful path on optional ones.
- Event shape: feed each handler a dict missing one required key; assert `TerminalError` + that the
  notify helper was invoked.
- Keep every new test co-located with its function and green before opening the PR.
- SPA (FR-006 → FR-010): most are memoization/identity changes verifiable via existing suites plus a
  targeted test for the FR-009 de-dupe guard; measure before adding `useMemo`/`useCallback` (react.md
  §15) and keep `npm run lint`/`test` green with no `exhaustive-deps` suppression.

## Implementation Phases

The Lambda phases (1–3) and the SPA phases (4–5) are independent and can land as separate PRs.

### Phase 1: Config init-validation (FR-001)

- Add a required/optional split + validation to both `config.py`; tests.

### Phase 2: Event-shape validation + thin handlers (FR-002, FR-004)

- Add shape checks raising `TerminalError` to the three handlers; wire `emit_failure`; delegate the
  fat `validate_authorize`/`check_table_absent` handlers to pure functions; tests.

### Phase 3: Type hints + Python-style cleanups (FR-003, FR-005)

- Annotate public signatures group by group; hoist `import jwt`, guard `messages.format`, `now_iso`
  via `datetime`; keep `ruff` green; optional local `mypy` pass.

### Phase 4: SPA identity/memoization cleanups (FR-006, FR-007)

- `useCallback`/`useMemo` the `SelectionProvider` value, `useConnections` return, and the
  `QueryWorkspace` derived structures/handlers; verify no re-render regressions.

### Phase 5: SPA robustness (FR-008, FR-009, FR-010)

- Harden the `useNotifications` timer cleanup; fix the `submit` de-dupe guard with a test; resolve the
  `QueryResultsTable` keys.
