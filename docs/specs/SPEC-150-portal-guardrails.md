---
type: Spec
id: SPEC-150
title: "Portal Guardrails — Typecheck Gate, Enqueue Re-entrancy & the Error-Code Contract"
description: "Closes ten portal guard gaps: declared strict typecheck, failing coverage floors, a null-safe error adapter, a chunk-404 error boundary, refresh double-click re-entrancy and unreachable not-configured messages."
spec_status: Completed
depends_on: [SPEC-106, SPEC-057, SPEC-145, SPEC-078, SPEC-149]
arc: audit-remediation
arc_order: 1
---

**Dependency notes:** SPEC-106 (`lib/errorMessages.ts`, `toUserMessage`, the `ErrorRule` shape and the `passthrough` mechanism this spec extends), SPEC-057 (the `athenaresults/` delete-deny acceptance criterion this spec finally meets), SPEC-145 (`useTableRefresh`, whose re-entrancy guard FR-003 replaces), SPEC-078 (the three run-scope keybindings FR-010 covers), SPEC-149 (the concurrent-refresh race FR-003 narrows from the browser side)
> **Reference:** this spec comes from a codebase audit (2026-08-05), not from a product need. Its unifying theme is **guards that exist in principle but do not hold in practice** — a strict-mode guarantee the project asserts but never declares, an error-mapping mechanism whose codes are never set, a re-entrancy guard written correctly in one hook and by state in its two siblings, an acceptance criterion recorded in SPEC-057 and never implemented, and a test double that cannot distinguish the three keybindings it exists to cover. Every item is a small, local change; the value is that each closes a hole something in the repo already claims is closed.
>
> **This is browser + CI only. No Lambda change, no IAM change, no infra change, no new env var, no new AWS call.** If a task in this spec starts editing `lambdas/` or `infra/`, it has gone wrong — the control-plane findings are deferred (see Out of Scope).
>
> **It already cost a red `main`, and the main fix has since landed.** On 2026-08-05, PR #361 (SPEC-145) merged with a type error in `SchemaBrowser.test.tsx`: lint, prettier and all 1301 tests passed, because `ci.yml` did not invoke the compiler. `Deploy App` on `main` failed at 03:10 with `error TS2322` and was fixed by #362 at 03:19. **PR #363 then added the gate** — `npm run build` on every PR — so FR-001 is now only the smaller half (declaring the inherited `strict` default), plus a one-off confirmation that the shipped gate really fails on that shape. Read `ci.yml`'s header comment before touching anything here: it documents a trap this spec's first draft missed.
>
> **Two things a reader will assume and should not.** First, **TypeScript `strict` is already ON** — `tsconfig.app.json` has no `"strict"` key, but TypeScript 6.0.3 defaults it true (`tsc --strict false` yields 157 errors; as-configured yields 0). Do not "enable strict" as part of this work; FR-001's related task is to *declare* the inherited default, which is a different and much smaller thing. Second, **`ProtectedObject` already exists** as a `passthrough` code (`errorMessages.ts:64`) and is already used by the prefix-marker delete guard — FR-007 reuses it rather than inventing a code.

## Overview

A codebase audit found the portal's engineering fundamentals strong — 1301 frontend tests and 1745 Lambda tests green, 96% Python coverage, no `any` in source, no dead exports, services returning `ServiceResult` everywhere, and `toUserMessage` used at every render site. What it also found is a consistent second-order pattern: **the repo builds a guard, documents it, and then leaves one caller, one config key, or one test double that does not honour it.** Individually each is a few lines. Together they are the difference between mechanisms that are designed correctly and mechanisms that actually hold.

This spec closes ten of them. Four are user-visible defects: six authored "not configured" messages that can never reach a user, an expired session that shows the wrong message on every S3-backed screen, a table refresh that a double-click can start twice, and a delete the UI offers on a folder IAM denies. Four are guards: a declared rather than inherited `strict`, coverage floors that fail rather than merely report, a null-safe error adapter, and an error boundary so a post-deploy chunk 404 is a reload instead of a white screen. Two are tests that assert what they claim to: an invariant covering the error-code contract that makes the whole mapper work, and keybinding coverage that can tell Cmd+Enter from Cmd+Shift+Enter.

None of this changes a user-facing feature. The measurable outcome is that the type guarantee stops depending on a compiler default, a misconfigured deploy names itself, and the refresh race SPEC-149 left open cannot be started from the browser by an impatient click.

---

## Scope

### In Scope

- **Declaring the `strict` default** that TypeScript 6 supplies implicitly, and a one-off confirmation that the already-shipped `Build` gate (#363) fails on the defect shape that motivated it.
- **Coverage thresholds** in both languages, ratcheted at today's measured numbers.
- **A ref-based re-entrancy guard** in `useTableRefresh` and `useTableShare`, adopting the pattern `useDataQualityCheck` already documents.
- **A `NotConfigured` error code and rule**, so the six authored "… is not configured" messages reach the user.
- **`code: 'NotAuthenticated'` on `getS3Client`**, by routing it through the existing `getSessionCredentials` rather than duplicating the credential fetch.
- **An invariant test** that no service returns a failure without a `code`.
- **A delete guard on a space's `athenaresults/`**, meeting SPEC-057's written acceptance criterion.
- **A top-level `ErrorBoundary`** around the lazy routes and the root layout.
- **Null-safety in `toServiceError` and `isNotFound`**, which currently throw on a non-object throw.
- **A DEV gate on the static-credential branch** of `s3Client.ts`, at the read rather than in the consumer.
- **Keybinding test coverage** for SPEC-078's three run scopes, including fixing the Monaco mock that makes them indistinguishable.
- **Help & guides sweep** per SPEC-074 — reviewed and expected to be a no-op, since no user-facing flow changes. Recording "checked, nothing to change" is the deliverable.

### Out of Scope

Each of the below is real and evidenced in the audit report; each is deferred because it belongs to a different plane, a different risk profile, or a different review surface. **Do not fold any of them into this spec.**

- **Every control-plane (Python) finding.** A single-file data-quality check profiling the parent folder and returning `verdict: "clean"` over an empty table; `teardown` freeing a space name while objects remain; `save_members` losing concurrent roster edits; `notifications-writer` discarding `Records[1:]`; unescaped DDL interpolation; `casio.is_precondition` missing 409. These want their own spec — they touch five Lambdas, two of them have data-loss consequences, and one needs a live check. **Now SPEC-151**, with the failure-notification half split into **SPEC-152** because it provisions infrastructure.
- **The meta-test blind spots** — `test_deploy_matrix.py` not checking the layer job's copy list against the layer directory (SPEC-137's actual shape), and pagination continuation being unexercised across the fleet. **Now SPEC-153.**
- **The untested user journeys** — table share end to end, sign-out, collision resolution through the UI, upload to completion, results pagination, remove-member. These are additive test work with no production change and should not gate the fixes here. **Now SPEC-154.**
- **The reuse cluster** — the six-times-duplicated S3 JSON reader, the eleven-site dialog chrome, the triplicated bulk-operation feedback stanza, and the two god components (`QueryWorkspace.tsx` at 1772 lines, `FileBrowser.tsx` at 1300). Pure refactor; it must not ride along with behaviour changes. **Now SPEC-155** (browser) and **SPEC-156** (Lambda layers).
- **`noUncheckedIndexedAccess`** (239 sites) — its own decision; two sites are load-bearing (`query.service.ts:168,268`). **mypy for `lambdas/`** lands report-only in SPEC-153.
- **Migrating `fireEvent` → `userEvent`** across the 50 fireEvent-only test files. §21 scopes its rule to "new/reworked tests"; this is opportunistic, not a project.
- **Changing what `athenaresults/` shows in the browser.** Its visibility is deliberate (`protectedFolders.ts:7-8`). FR-007 blocks the *delete*, nothing else.
- **Any change to the notifications pipeline, the `Notification` type, or any control-plane message.**

---

## Functional Requirements

### FR-001: The inherited `strict` default is declared, not assumed

#### Description

> **The typecheck gate itself has already shipped — PR #363, `ci: run npm run build on PRs so type errors fail pre-merge`, merged 2026-08-05.** It runs `npm run build` before the test step and rewrote the stale comment, and it found something this spec's first draft had not: `tsc --noEmit -p apps/portal/tsconfig.json` **exits 0 having checked nothing**, because that config is solution-style (project references only, no `files`/`include`). `tsc -b` is the only invocation that covers the app and its tests. Do not re-add a gate; read `ci.yml`'s header comment first.

What remains is the smaller half. `tsconfig.app.json` and `tsconfig.node.json` have **no `strict` key** — verified still absent on `main`. Strict is nonetheless on, because TypeScript 6.0.3 defaults it true. The project therefore depends on a compiler default for its single most important type guarantee, in a repo that has already been burned once by exactly that: `pyproject.toml` records at length how ruff 0.16 widened its own default rule set overnight and turned `main` red, and concludes "THE RULE SET IS CHOSEN HERE, NOT INHERITED."

#### Acceptance Criteria

- [ ] `tsconfig.app.json` and `tsconfig.node.json` each gain an explicit `"strict": true`.
- [ ] Adding the key changes **no** error count — `npx tsc -b` exits 0 before and after. It is a declaration of the current default, not a new constraint. If it *does* produce errors, stop: the premise in the Reference note is wrong and the finding needs re-deriving.
- [ ] A comment at the key records why it is stated rather than inherited, pointing at `pyproject.toml`'s ruff block as the precedent.
- [ ] `npm run build` and the CI `Build` step remain green.
- [ ] **No change to `ci.yml`.** The gate is already correct and its header comment already explains the `tsc -b` subtlety better than this spec could restate it.

### FR-001a: Confirm the shipped gate catches the defect it was built for

#### Description

A one-off verification, not code. #363 landed without a demonstration that it fails on the shape that motivated it.

#### Acceptance Criteria

- [ ] On a scratch branch, reintroduce the #361 defect (remove `onRefreshTable` from `makeActions` in `SchemaBrowser.test.tsx`), push, and confirm the `ci` job **fails** at the `Build` step.
- [ ] Delete the scratch branch. Nothing is merged from it.
- [ ] The result is recorded in the delivery doc. If the gate does **not** fail, that is a finding that outranks everything else in this spec.

### FR-002: Coverage floors fail rather than report

#### Description

Both suites measure coverage and neither gates on it, so deleting tests passes CI identically to keeping them. Ratchet at today's measured values.

#### Acceptance Criteria

- [ ] `apps/portal/vite.config.ts` gains `test.coverage.thresholds` set to the **current measured** values rounded **down** to the nearest whole percent: statements 90, branches 86, functions 89, lines 92.
- [ ] `pyproject.toml`'s `addopts` gains `--cov-fail-under=95` (current: 96).
- [ ] `npm run test:coverage` and `pytest lambdas/` both still pass unchanged on a clean tree.
- [ ] Lowering any threshold value in a later PR is a visible one-line diff — no threshold is computed, inherited, or read from a file.
- [ ] A comment on each records that these are **ratchets at the measured level, not targets**, and are to be raised when coverage rises, never lowered to accommodate a regression.

### FR-003: Enqueue hooks guard re-entry with a ref, not state

#### Description

`useTableRefresh.ts:87` and `useTableShare.ts` both guard with `if (!target || busy) return`, where `busy` is React state. Two clicks landing in the same render both read `busy === false` and enqueue twice. `useDataQualityCheck.ts:56-58` already solves this with a ref and documents the reasoning. Because `tableBuild.service.ts` mints `deduplicationId: crypto.randomUUID()` per call, SQS FIFO dedup cannot collapse the duplicate, and `messageGroupId` serializes delivery but not execution — so a double-click starts two overlapping `UpdateTable` runs on one table, which is exactly the race CLAUDE.md records as surviving SPEC-149.

#### Acceptance Criteria

- [ ] `useTableRefresh` guards re-entry with a `useRef<boolean>`, set before the first `await` and cleared in a path that runs on **every** exit, including the error and early-return paths.
- [ ] `useTableShare` receives the identical guard.
- [ ] The `busy` state remains and continues to drive the disabled button and busy label — the ref is the correctness guard, the state is the visible one. Neither replaces the other.
- [ ] A test for each hook drives **two `submit` calls within a single act block, without awaiting between them**, and asserts the enqueue service was called **exactly once**. A test that awaits the first call before making the second does not satisfy this criterion — it would pass against the current state-based guard.
- [ ] Each hook's second call resolves without throwing and leaves the hook in a usable state (a subsequent legitimate submit still works).
- [ ] The ref guard carries a one-line comment pointing at `useDataQualityCheck`'s explanation rather than restating it.

### FR-004: A `NotConfigured` code, so "not configured" reaches the user

#### Description

`lib/enqueueFifo.ts:47-49` returns `{success: false, error: {message: notConfiguredMessage}}` with no `code`. `toUserMessage` keys on `code ?? name`; with neither, it falls through the five `MATCH_RULES` patterns (none of which matches "is not configured") to `GENERIC`. All six authored strings are therefore unreachable text, and a missing `VITE_*_QUEUE_URL` — the documented deploy gotcha — presents as "Something went wrong. Contact the Administrator."

#### Acceptance Criteria

- [ ] `CODE_RULES` gains `{code: 'NotConfigured', userFixable: false, passthrough: true}`.
- [ ] `enqueueFifo` sets `code: 'NotConfigured'` on the missing-queue-URL failure.
- [ ] `toUserMessage({code: 'NotConfigured', message: 'Table refresh is not configured'})` returns that exact message, not `GENERIC`. Asserted by test.
- [ ] All six call sites are verified to surface their own wording: `sharedSpaces.service.ts:40`, `dataQuality.service.ts:47`, `tableShare.service.ts:38`, `notifications.service.ts:104`, `tableBuild.service.ts:23` and `:58`. One test may cover them as a table.
- [ ] `passthrough` is correct here for the reason the `ErrorRule` doc comment states — the message is authored by our own service layer and embeds no AWS text. The rule carries a short comment saying so.

### FR-005: `getS3Client` reports `NotAuthenticated` like its siblings

#### Description

`lib/s3Client.ts:57-62` returns the no-credentials failure **without** a code; `lib/awsCredentials.ts:16-20` returns the identical message **with** `code: 'NotAuthenticated'`, for which a rule exists (`errorMessages.ts:104` → "Sign in to continue."). Athena, Glue and SQS route through `awsCredentials` and get the right message; S3 does not — so the file browser, notifications, saved queries, query history and every data-quality view show the generic on a lapsed session. The divergence exists because `getS3Client` duplicates the credential fetch instead of reusing it.

#### Acceptance Criteria

- [ ] `getS3Client` obtains credentials via `getSessionCredentials(forceRefresh)` rather than calling `fetchAuthSession` itself, matching `athenaClient.ts`, `glueClient.ts` and `sqsClient.ts`.
- [ ] A lapsed session reaching any S3-backed surface yields "Sign in to continue." Asserted by a test on `getS3Client` that mocks the credential source and checks the mapped message, not just the code.
- [ ] The dev/unauthenticated static-credential path (`s3Client.ts:5,34-41`) and the existing `forceRefresh` retry contract used by `withCredentialRetry` both still behave identically — covered by the existing `s3Client.test.ts` and `credentialRetry.test.ts` passing unchanged.
- [ ] No behavioural change to the three sibling clients.

### FR-006: No service returns a failure without a `code`

#### Description

FR-004 and FR-005 are two instances of one class: `toUserMessage`'s entire design rests on failures carrying a `code`, and nothing enforces that. Encode the invariant so the next omission fails a test instead of shipping a generic message.

#### Acceptance Criteria

- [ ] A test asserts that every `{success: false}` value produced by the app's service layer carries a non-empty `error.code`.
- [ ] The test is **enumerative, not sampled** — it derives its subject list from the exported functions of `src/**/*.service.ts` plus `src/lib/*Client.ts`, so a newly added service is covered without editing the test. If a genuinely dynamic subject cannot be enumerated, the test instead asserts over every failure path the existing suites already exercise, and a comment records the narrower guarantee.
- [ ] Any deliberate exemption is an explicit named allowlist entry with a one-line reason, not a silent skip.
- [ ] The test fails if FR-004's `code` is removed from `enqueueFifo`. Verified by temporarily reverting, then restoring.

### FR-007: Deleting a space's `athenaresults/` is refused in the UI

#### Description

`portal-role-analytics.json.tftpl:61-66` (`Sid: ResultsNoDelete`) denies `s3:DeleteObject` under `athenaresults/*`. The folder is deliberately visible in the browser (`protectedFolders.ts:7-8`) but no delete guard exists, so Delete is enabled and the user gets "You don't have permission to do that. Contact the Administrator." for a rule the app itself authored. **SPEC-057:97-98 already states the UI "refuses to delete … the space's `athenaresults/`"** — this is an unmet acceptance criterion, not a new feature.

#### Acceptance Criteria

- [ ] Deleting the `athenaresults/` folder at a space root is refused **client-side, before any S3 request**, returning `code: 'ProtectedObject'` with authored wording naming query results (e.g. "Query results are managed for you and can't be deleted.").
- [ ] The guard reuses the existing `isRootFolderNamed(folderPrefix, rootPrefix, names)` helper and follows the prefix-marker precedent at `fileBrowser.service.ts:219-227`.
- [ ] The guard applies at the **space root only** — a user's own nested folder that happens to be named `athenaresults` is a normal folder and remains deletable. Asserted by a test for each case.
- [ ] The guard holds identically in a **shared space** as in the personal space, which is the form SPEC-057 states it in.
- [ ] The move guard on the same folder is covered by the same criterion where `moveObject`'s **source** is that folder. If it is out of reach without wider change, it is recorded here as deliberately deferred rather than silently skipped.
- [ ] No change to the folder's visibility in the browser or to `PICKER_LOCKED_FOLDERS`.
- [ ] Because `ProtectedObject` is already a `passthrough` code, no new rule is added to `errorMessages.ts`.

### FR-008: A render throw is a reload, not a white screen

#### Description

The repo has no `ErrorBoundary`, `componentDidCatch` or `getDerivedStateFromError` anywhere. `deploy-app.yml:132-139` documents an accepted race in which a user with the SPA already open triggers a lazy import after the deploy's delete pass has removed the old chunk, "and gets a 404 inside a Suspense boundary" — with no boundary, that rejected import unmounts the whole tree.

#### Acceptance Criteria

- [ ] A reusable `ErrorBoundary` lives in `src/components/`, is a named export, and renders a fallback offering a **reload** action.
- [ ] It wraps each lazy route's `Suspense` (`App.tsx:43`, `:51`) and the root layout, so both a chunk-load rejection and an ordinary render throw are contained.
- [ ] A test renders a child that throws and asserts the fallback appears with an accessible reload control, and that the surrounding chrome (nav/header) survives where the boundary is scoped below it.
- [ ] The fallback's wording goes through the same authored-copy discipline as the rest of the app — it must not render `error.message`.
- [ ] The boundary does not swallow the error silently: it logs via the existing dev-only logging discipline, not an ungated `console.error`.
- [ ] `vitest-axe` assertions cover the fallback, per the project's a11y practice.

### FR-009: The error adapters survive a non-object throw

#### Description

`serviceResult.ts:48-49` and `lib/s3Errors.ts:20-21` dereference the caught value without a guard, so `toServiceError(null, …)` raises a `TypeError` from **inside a `catch`**, in functions documented as never throwing. `errorMessages.ts:189` guards correctly, which shows the case was considered once.

#### Acceptance Criteria

- [ ] `toServiceError` returns a well-formed `ServiceResult` failure — with its fallback message and no throw — for each of `null`, `undefined`, a string, and a number.
- [ ] `isNotFound` returns `false` rather than throwing for the same four inputs.
- [ ] Behaviour for a normal `Error` and for an AWS SDK error object is unchanged, asserted by the existing tests continuing to pass.

### FR-010: The three run-scope keybindings are covered by tests that can tell them apart

#### Description

`SqlEditor.tsx:161,165,168` registers Cmd+Enter (statement), Cmd+Shift+Enter (whole script) and Cmd+Alt+Enter (selection). The Monaco mock at `SqlEditor.test.tsx:20` is `KeyMod: {CtrlCmd: 2048}` — **no `Shift`, no `Alt`** — so both modifiers are `undefined`, coerce to `0`, and **all three register the identical binding `2051`**. The receiving spy is created inline and discarded (`onMount({addCommand: vi.fn()}, …)`), so nothing is asserted. Dropping a binding or swapping two scopes passes green today, on the primary way users run a query.

#### Acceptance Criteria

- [ ] The Monaco mock's `KeyMod` supplies **distinct non-zero** values for `CtrlCmd`, `Shift` and `Alt`, such that the three composed bindings are three different numbers.
- [ ] The `addCommand` spy is captured, not discarded, and the test asserts **exactly three** commands are registered with three **distinct** keybinding values.
- [ ] Invoking the handler registered for each binding calls the matching prop — `onRun`, `onRunScriptTabs`, `onRunScriptSingle` — asserted per scope, so swapping two registrations fails.
- [ ] The `QueryWorkspace` `SqlEditor` stub is widened to accept and expose the run props it currently discards (`QueryWorkspace.test.tsx:24` types only `{value, onChange}`), so deleting `onRun` at the call site cannot pass.
- [ ] The stub's exception comment is preserved and updated — it remains the sanctioned §21 heavy-child exception, now with a stated reason for the widened surface.
- [ ] Scope names in assertions match SPEC-078's vocabulary, so the test reads as the spec's contract rather than as the implementation's.

### FR-011: The dev credential path is gated where it is read, not where it is used

#### Description

`lib/s3Client.ts:5,34-41` reads `VITE_AWS_ACCESS_KEY_ID` and `VITE_AWS_SECRET_ACCESS_KEY` at **module scope** with no `import.meta.env.DEV` guard; the DEV gate lives one layer up in the *consumer* (`fileBrowser.service.ts:34`). Vite statically replaces `import.meta.env.VITE_*` with a literal at build time, so any build where the secret is set would inline it into the bundle regardless of mode. Nothing ships today — `deploy-app.yml` does not pass those vars, so Vite inlines `undefined` and the ternary dead-code-eliminates — which makes this **latent**. But the protection is an omission rather than a control, and this spec is about exactly that distinction.

#### Acceptance Criteria

- [ ] The static-credential branch in `s3Client.ts` is wrapped in `import.meta.env.DEV`, so a production build eliminates it whether or not the variables are set.
- [ ] A production-mode build (`npm run build`) contains **neither** `VITE_AWS_SECRET_ACCESS_KEY`'s value nor the credential-object literal, verified by grepping the emitted bundle with the variables deliberately set in the build environment. This check is the acceptance evidence and is recorded in the delivery doc.
- [ ] The dev unauthenticated path continues to work in `npm run dev` with the variables set.
- [ ] The existing `s3Client.test.ts` passes unchanged.
- [ ] A comment records that the gate belongs here — at the read — rather than in the consumer, and why.

### FR-012: User-facing documentation sweep

#### Description

SPEC-074 requires a Help & guides pass on anything a user can see. This spec changes error *wording* users encounter but adds no flow.

#### Acceptance Criteria

- [ ] `apps/portal/src/features/help/helpContent.ts` is reviewed against FR-004, FR-005 and FR-007.
- [ ] Any guide step that tells a user query results can be deleted, or that describes a misconfiguration symptom, is corrected.
- [ ] If nothing needs changing, the delivery doc records "checked, no change" explicitly. Silence is not an acceptable outcome.

---

## Interface Contract

```ts
// src/lib/errorMessages.ts — added to CODE_RULES (FR-004)
{code: 'NotConfigured', userFixable: false, passthrough: true},

// src/lib/enqueueFifo.ts (FR-004)
if (!queueUrl) {
  return {success: false, error: {message: notConfiguredMessage, code: 'NotConfigured'}};
}

// src/lib/s3Client.ts (FR-005) — reuse, don't duplicate
const credentials = await getSessionCredentials(forceRefresh);
if (!credentials.success) return credentials;   // carries code: 'NotAuthenticated'

// src/features/table-builder/useTableRefresh.ts (FR-003)
const inFlight = useRef(false);
// A ref, not `busy`: see useDataQualityCheck for why the state read loses the race.
if (inFlight.current) return;

// src/components/ErrorBoundary.tsx (FR-008)
export function ErrorBoundary({children, fallback}: {
  children: ReactNode;
  fallback?: ReactNode;
}): ReactElement;
```

No new types are introduced. `ServiceResult`, `ErrorRule` and `UserFacingMessage` are unchanged in shape — FR-004 adds a rule, not a field.

## Environment Variables

None. This spec introduces no new configuration.

## File & Folder Structure

```
.github/workflows/ci.yml                          # FR-001: Typecheck step
apps/portal/tsconfig.app.json                     # FR-001: explicit "strict": true
apps/portal/tsconfig.node.json                    # FR-001: explicit "strict": true
apps/portal/vite.config.ts                        # FR-002: coverage.thresholds
pyproject.toml                                    # FR-002: --cov-fail-under
apps/portal/src/
├── components/
│   ├── ErrorBoundary.tsx                         # FR-008 (new)
│   └── ErrorBoundary.test.tsx                    # FR-008 (new)
├── lib/
│   ├── errorMessages.ts                          # FR-004
│   ├── enqueueFifo.ts                            # FR-004
│   ├── s3Client.ts                               # FR-005
│   ├── serviceResult.ts                          # FR-009
│   ├── s3Errors.ts                               # FR-009
│   └── serviceErrorContract.test.ts              # FR-006 (new)
├── features/
│   ├── table-builder/useTableRefresh.ts          # FR-003
│   ├── table-share/useTableShare.ts              # FR-003
│   ├── file-browser/fileBrowser.service.ts       # FR-007
│   ├── query/SqlEditor.test.tsx                  # FR-010
│   ├── query/QueryWorkspace.test.tsx             # FR-010 (stub widened)
│   └── help/helpContent.ts                       # FR-012 (if needed)
└── App.tsx                                       # FR-008 (boundary placement)
```

## Implementation Phases

Phases are ordered so the gates land first — every later phase is then protected by them. Each is a reviewable unit; the build session generates and validates a plan against this spec before writing code.

### Phase 1: The CI gates

- Add explicit `"strict": true` to both tsconfigs with the rationale comment; confirm the error count is unchanged (FR-001).
- Add `coverage.thresholds` to `vite.config.ts` and `--cov-fail-under` to `pyproject.toml` at the measured values (FR-002).
- Run the one-off scratch-branch confirmation that the shipped `Build` gate fails on the #361 shape, then delete the branch (FR-001a).
- **Do not add a typecheck step** — PR #363 already did, and its header comment explains why `tsc -b` is the only invocation that works.

### Phase 2: The error-code contract

- Add the `NotConfigured` rule and set the code in `enqueueFifo` (FR-004).
- Route `getS3Client` through `getSessionCredentials` (FR-005), and gate its static-credential branch on `import.meta.env.DEV` (FR-011) — same file, same review.
- Make `toServiceError` and `isNotFound` null-safe (FR-009).
- Add the no-failure-without-a-code invariant test (FR-006), which should now pass and would have failed before the first two tasks.

### Phase 3: Enqueue re-entrancy

- Add the ref guard to `useTableRefresh` and `useTableShare` (FR-003).
- Add the same-render double-submit tests for both.

### Phase 4: The protected-folder delete guard

- Add the `athenaresults/` root guard to the delete path, reusing `isRootFolderNamed` (FR-007).
- Cover personal and shared space, and the nested-folder-of-the-same-name negative case.
- Resolve the move-source question one way or the other and record the outcome.

### Phase 5: The error boundary

- Build `ErrorBoundary` with its reload fallback and dev-only logging (FR-008).
- Place it around the two lazy routes and the root layout.
- Add behaviour and `vitest-axe` tests.

### Phase 6: Keybinding coverage

- Fix the Monaco mock's `KeyMod` and capture the `addCommand` spy (FR-010).
- Assert three distinct bindings and per-scope dispatch.
- Widen the `QueryWorkspace` `SqlEditor` stub to expose the run props.

### Phase 7: Completion

- FR-012 documentation sweep.
- Completion ritual per `CLAUDE.md`: status, INDEX row, delivery doc, component-inventory row for `ErrorBoundary`, and a Key Decisions line **only if** the build produces a genuinely new architectural decision. FR-001 reverses a documented trade-off, so that one is worth a decisions entry; the rest are bug fixes and are not.
