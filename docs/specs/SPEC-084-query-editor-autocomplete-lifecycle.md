# Spec: Query Editor Autocomplete Lifecycle Fix (Monaco completion provider)

**ID:** SPEC-084
**Status:** Draft
**Last Updated:** 2026-07-02
**Depends On:** SPEC-035 (Monaco SQL editor), SPEC-047 (schema-aware completions)

## Overview

The SQL editor's schema-aware autocomplete is registered as a **module-level singleton** Monaco
completion provider (`completionDisposable` in `apps/portal/src/features/query/SqlEditor.tsx`),
created lazily in Monaco's `onMount` via `registerSqlCompletionsOnce`. Its disposal, however, is
tied to a **per-component-instance** `useEffect(() => () => {…}, [])` cleanup that calls
`completionDisposable.dispose()` and sets it back to `null`.

Because the provider is registered against the Monaco `languages` **global** (shared across every
editor of that language) but disposed on any single editor instance's unmount, the lifecycle is
fragile: under React StrictMode's dev mount→unmount→remount, and on real query-tab switches that
unmount/remount the editor, the cleanup can dispose the singleton while `onMount` may not
re-register on a reused Monaco instance — leaving autocomplete **silently dead** after a tab
switch, or conversely stacking a duplicate provider. `react.md` §10/§11 call this out directly:
Effects must be resilient to being run repeatedly, and a singleton nulled on cleanup is exactly the
hazard. This spec makes the provider's registration and disposal robust to repeated mount/unmount.

## Scope

### In Scope

- Rework the completion-provider lifecycle in `SqlEditor.tsx` / `sqlCompletions.ts` so registration
  happens once and survives editor unmount/remount (tab switches) and StrictMode double-invocation,
  with no duplicate providers and no dead-autocomplete state.
- A test that reproduces the regression (mount → unmount → remount, then assert the provider is
  registered exactly once and still functional) so it can't silently return.

### Out of Scope

- Changing completion *content* / ranking (`buildSqlCompletions`, `createSqlCompletionProvider`
  behavior) — only its registration lifecycle.
- Any change to how the active-database schema is fed to the provider
  (`completionSchemaRef` ref-forwarding) beyond what the lifecycle fix requires.
- Broader Monaco worker/self-hosting setup (SPEC-035).

---

## Functional Requirements

### FR-001: Completion provider survives editor remount

#### Description:

The schema-aware completion provider must remain registered and functional across query-tab
switches (which unmount and remount `SqlEditor`) and across StrictMode's dev mount→unmount→remount,
without stacking duplicates. Tie the provider's lifetime to the Monaco/app lifetime (register once,
don't dispose on a single component instance's unmount) or ref-count registrations, rather than
disposing the shared singleton on the first instance teardown.

#### Acceptance Criteria:

- [ ] After opening a query, switching to another tab, and returning, autocomplete still produces
      schema-aware suggestions.
- [ ] The provider is registered **exactly once** regardless of how many times `SqlEditor` mounts
      and unmounts; no duplicate suggestions appear.
- [ ] Under React StrictMode (dev), no "disposed then never re-registered" gap occurs.
- [ ] The latest active-database schema still reaches the provider after a remount (the
      ref-forwarding contract is preserved).

### FR-002: Regression coverage

#### Description:

Add a test that exercises the mount→unmount→remount sequence and asserts the invariant, so the
lifecycle bug cannot silently reappear.

#### Acceptance Criteria:

- [ ] A test mounts the editor, unmounts it, remounts it, and asserts the completion provider is
      registered once and still active (e.g. by spying on the register/dispose calls).
- [ ] `npm run lint` / `npm run test` green; no suppressed `react-hooks/exhaustive-deps`.

---

## Implementation Notes

- Current shape (`SqlEditor.tsx`): `let completionDisposable` module global, `registerSqlCompletionsOnce`
  guards with `if (completionDisposable) return`, `handleMount` calls it, and a `useEffect(…, [])`
  cleanup disposes + nulls it. The disposal-on-instance-unmount is the defect.
- Options to weigh during the design/plan step: register at module load / first-mount and never
  dispose on component unmount (simplest — the provider is app-global anyway); or ref-count active
  editor instances and dispose only when the count hits zero. Pick one and document why.

## Implementation Phases

### Phase 1: Lifecycle rework + test

- Change the registration/disposal so it's remount-safe; add the regression test; verify autocomplete
  works after a tab switch in the running app (preview) and under StrictMode.
