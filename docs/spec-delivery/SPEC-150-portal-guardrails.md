# Completed Spec — SPEC-150: Portal Guardrails — Typecheck Gate, Enqueue Re-entrancy & the Error-Code Contract

## What was completed?

Ten guards the repo already claimed were closed, actually closed. Browser + CI only — no Lambda,
IAM, infra or env-var change, as the spec required.

- **The `strict` default is declared** in `tsconfig.app.json` / `tsconfig.node.json`. `tsc -b` exits
  0 before and after, as predicted — this states an inherited default rather than adding a constraint.
- **Coverage floors** — `vite.config.ts` `test.coverage.thresholds` at **91/86/89/93** and
  `pyproject.toml` `--cov-fail-under=95`, each a literal, each commented as a ratchet not a target.
- **Ref-based re-entrancy** in `useTableRefresh` and `useTableShare`, adopting `useDataQualityCheck`'s
  documented pattern. `busy` state stays as the visible guard.
- **`NotConfigured`** rule + code in `enqueueFifo` (`errorMessages.ts`, `enqueueFifo.ts`).
- **`getS3Client` routed through `getSessionCredentials`**, deleting its duplicate `fetchAuthSession`.
- **`serviceErrorContract.test.ts`** — the no-failure-without-a-code invariant.
- **`athenaresults/` delete + move-source refusal** (`protectedFolders.ts`
  `UNDELETABLE_ROOT_FOLDERS` / `isUndeletableRootFolder`, guards in `fileBrowser.service.ts`).
- **`components/ErrorBoundary.tsx`** — reusable, reload fallback, wrapping both lazy routes and
  `RootLayout`'s `Outlet`.
- **Null-safe `toServiceError` / `isNotFound`** (and `auth.service`'s local `toError`).
- **DEV gate at the READ** of `VITE_AWS_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` in `s3Client.ts`.
- **Real keybinding coverage** — the Monaco `KeyMod` mock and the `addCommand` spy in
  `SqlEditor.test.tsx`; the widened `SqlEditor` stub in `QueryWorkspace.test.tsx`.

### FR-001a — the gate confirmation (the one-off this spec owed)

Scratch branch `spec-150-fr001a-gate-proof` reintroduced the #361 defect (`onRefreshTable` removed
from `makeActions` in `SchemaBrowser.test.tsx`) on PR #374. **The `ci` job failed at `Build
(typecheck + bundle)`** with `TS2322` at `SchemaBrowser.test.tsx(32,3)`, while **Lint and Format
check passed and Test was *skipped***. That combination is the finding: under the pre-#363 config
every check would have been green. PR closed, branch deleted, nothing merged.

### FR-011 — the credential-inlining evidence

The spec called this **latent**; it is not. Building with the variables deliberately set
(`VITE_AWS_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY`), the **pre-change** bundle contains **both the
access key and the secret** in `dist/assets/shared-spaces-*.js`; the gated build contains neither.
Nothing shipped only because `deploy-app.yml` never passed them — the protection was absent, not
merely unexercised. (`secretAccessKey:` still appears in that chunk: AWS SDK Cognito-identity
internals, not our literal.)

### Deliberate deviations

- **Coverage floors are 91/86/89/93, not the spec's 90/86/89/92.** Measured coverage rose between
  spec-writing and build (91.33 / 86.68 / 89.49 / 93.35). Ratcheting at *today's* measurement is what
  FR-002's rationale asks for, and was confirmed with the user. Python's 95 was already today's
  number floored (95.58%).
- **FR-006 found six more codeless failures than the two the spec named**, all fixed rather than
  allowlisted, so the allowlist ships **empty**. Three were `'Not signed in'` in the shared-space
  hooks — the same user-visible defect as FR-005, showing GENERIC where "Sign in to continue."
  belongs. The others (`query.service` ×2, `notifications.service` ×1) are coded and *deliberately*
  map to GENERIC: they are internal faults with no user remedy, and the code exists so the mapper
  decides that rather than a fallthrough.
- **FR-006's test is a source-text scan, not a call-the-exports scan.** Service functions cannot be
  invoked generically (each needs its own AWS boundary and arguments). It derives subjects from
  `import.meta.glob`, so a new service file is covered with no edit, and it asserts the glob is
  non-empty so a broken scan cannot read as clean. The narrower guarantee — it cannot prove the code
  is non-empty at *runtime*, since the adapters assign `code: e.name` — is recorded in the file.
- **`auth.service.ts`'s local `toError` got FR-009's guard too**, though the FR names only two
  functions. It is the identical crash-inside-a-catch. Deleting the duplicate belongs to SPEC-155.
- **FR-007 needed `rootPrefix` threaded** through `useDelete` / `useMove` from `FileBrowser`, and
  made **required** on `deleteFolder` / `moveFolder`. `username` identifies the *personal* root only,
  so a username-derived guard would have silently missed every shared space — the form SPEC-057
  states the criterion in. Required (not optional) so the typechecker names any call site that omits it.
- **The move-source guard was resolved as DONE, not deferred.** A move is a copy plus a delete of the
  source, so the same refusal applies; the folder was already locked out as a *destination*.
- **FR-012 was not a no-op.** FR-007 shipped a user-visible refusal, so the Files "Rename, move, copy,
  or delete" guide gained one step naming `athenaresults` as managed and undeletable. The Query
  guide's three documented shortcuts were checked against `SqlEditor.tsx` and are correct — and are
  now test-backed for the first time.

### What the fresh-context review changed

The review found one real defect and four tightenings, all fixed before merge:

- **The `RootLayout` boundary never reset.** `RootLayout` is a *layout* route, so its
  `ErrorBoundary` instance outlives child-route changes and nothing cleared `hasError` — once an
  eagerly-loaded page threw, navigating away left the nav visible but the content region stuck on the
  fallback until a reload. Its own comment claimed the opposite. Fixed with `key={pathname}`, and
  **pinned by a test that fails without it**. The two `App.tsx` boundaries never had this: they live
  in a route `element` and unmount on navigation. Note the first attempt at that test passed against
  the bug — re-rendering a second `MemoryRouter` does not change the route, because `initialEntries`
  applies at mount only. It now drives a real in-router navigation.
- **FR-006's scan could be fooled by a `code:` in a comment or a string.** This codebase writes
  explanatory comments *inside* the returned object, so that was a live hole. Comments and string
  bodies are now blanked before scanning, the property match is position-anchored, `success : false`
  (spaced) matches, and six self-tests assert the scanner detects what it claims to. The file's
  "narrower guarantee" note now enumerates all three residual limits rather than one.
- **Six more unguarded catch dereferences** — `awsCredentials.ts` ×2, `fileBrowser.service.ts` ×2,
  `glue.service.ts` ×2. `awsCredentials` is the one that mattered: FR-005 had just routed *all* S3
  traffic through it. The FR-009 class is now closed portal-wide.
- **`rootPrefix` made required on `useDelete`/`useMove`** rather than defaulting to the browsed
  prefix. The fallback was safe with today's single caller, but a future caller omitting it while
  inside `alice/reports/` would have made `alice/reports/athenaresults/` falsely undeletable — the
  inverse of the bug FR-007 fixes.

Also confirmed by the review and worth recording: `copyFolder` is deliberately **not** guarded (IAM
denies only `DeleteObject`, so copying results out is legitimate), and `Timeout` at
`query.service.ts:218` intentionally reuses the existing rule.

## What changed from earlier specs?

- **SPEC-057's acceptance criterion (:97-98) is finally met** — the UI refuses to delete a space's
  `athenaresults/`. Client-side, before any S3 request, `code: 'ProtectedObject'`.
- **SPEC-149's concurrent-refresh race is narrowed from the browser side.** It is *not* closed —
  Glue still offers no compare-and-set on `UpdateTable`, and SPEC-157 owns the real fix. What is
  closed is a double-click starting the pair: `deduplicationId` is a fresh UUID per call, so SQS FIFO
  could never have collapsed it.
- **`deleteFolder` / `moveFolder` signatures gained a required `rootPrefix`** (SPEC-019 primitives).
- **SPEC-145's `useTableRefresh` and SPEC-093's `useTableShare`** swapped a state guard for a ref.
- **SPEC-141's documented deploy race now has a boundary under it** — the 404-inside-Suspense it
  accepts no longer unmounts the tree.

## Verification

Local: `npm run format`, `npm run lint`, `npm run build` (`tsc -b`) and **1491 frontend tests** green;
`pytest lambdas/` 1772 passed at 95.58% against the new floor. Every new guard was verified by
**counterfactual** rather than by passing: the FR-006 invariant re-flagged `enqueueFifo` with the code
removed; both FR-003 tests fail against the old state guard; FR-010's tests fail on both a swapped and
a dropped binding, and the widened stub fails when `onRunScriptTabs` is deleted at the call site;
FR-011's grep was run against both the gated and ungated builds. FR-001a ran on real CI (#374).

Nothing is deferred to deploy — this spec provisions nothing. The `ErrorBoundary`'s real trigger (a
post-deploy chunk 404) cannot be staged locally; the boundary is covered by an induced render throw
plus `vitest-axe` on the driven fallback container.
