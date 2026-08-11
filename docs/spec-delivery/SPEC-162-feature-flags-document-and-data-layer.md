# Completed Spec — SPEC-162: Feature Flags — Document, Publish Pipeline & Browser Data Layer

## What was completed?

A git-controlled feature-flag document, a publish pipeline that puts it in front of the browser, and
the data layer that resolves it. **Nothing reads the result yet** — that is SPEC-163, and it is the
intended shape of the split.

- **The document.** `config/feature-flags.json` — `version`, a total `defaults` block (four flags,
  all `true`) and per-environment partial overrides (`prod`, today). The only place a flag is edited.
- **The validator.** `scripts/validate_feature_flags.py`, standard library only, run on every PR
  (`ci.yml`) and again immediately before the upload. Rejects an unknown version, an unknown flag
  key, a non-boolean value, an incomplete `defaults`, and either half of a target/environment
  mismatch.
- **The publish pipeline.** `.github/workflows/deploy-config.yml` — on `config/**` pushes and manual
  dispatch, one `aws s3 cp` to `_config/feature-flags.json` with `Cache-Control: no-cache`.
  Independent of an app build, so flipping a flag is not a redeploy.
- **The browser layer.** `features/feature-flags/` — `getFeatureFlags`, `useFeatureFlags`,
  `FEATURE_FLAG_DEFAULTS`, `featureFlagKeys`, and the types. `VITE_ENVIRONMENT` wired through
  `env.ts`, `.env.example`, `deploy-app.yml` and the GitHub repo variable (set to `prod`).
- **IAM.** One `ReadTheFeatureFlags` Sid: `s3:GetObject` on `{user-space}/_config/*`. No write, no
  `ListBucket` widening, no deploy-role statement, no CORS/CSP/bucket-policy change.

### `ProtectedLayout` mounts the hook and discards the result — that is not a placeholder

"Nothing reads the flags" is true of the *resolved set*; it must not be true of the *read*. Without a
mount, Rollup drops the entire feature from the production bundle (verified: `_config/`, the error
code and the flag names were all absent from `dist/` before this was added, present after) — and then
the `_config/*` grant, the bucket-policy allowlist, the CORS preflight, the CSP `connect-src` entry,
the key spelling and the credential timing are **all unexercised in production while every gate is
green**. That is SPEC-137's shape. It is also what makes FR-009 performable at all: the live check
observes this request, and it cannot observe one that nothing issues.

Pinned by `ProtectedLayout.test.tsx` in both directions — the read happens when signed in, and does
not when signed out — so the call cannot be removed as dead code.

### A note for SPEC-163

Signed out, `status` is `'loading'` forever (the query is gated on a user). A gating consumer must
treat `'loading'` as **render all-on**, never as "wait" — a skeleton keyed on it would spin
indefinitely on any surface reachable while signed out.

### Deliberate deviations

- **`getFeatureFlags` takes `string | undefined`**, not the spec's `string`. FR-007 requires an
  unwired `VITE_ENVIRONMENT` to resolve rather than crash, and `envVar` returns `undefined` for an
  unset variable — passing `''` to satisfy the declared signature would have been a lie about an
  environment name.
- **The validator reads the publish workflow's matrix** instead of taking a target list. FR-002
  requires the check in both directions, and a list handed to the script by the same workflow that
  declares it would be comparing a copy of the answer with itself.
- **The FR-006 tripwire and the defaults-match-the-document test live in
  `featureFlags.service.test.ts`**, not in a separate file; both are statements about the service
  layer's boundary, and the spec's file list named no home for them.
- **Sources are swept with `import.meta.glob('…', {query: '?raw'})`, not `node:fs`.** The portal's
  `tsconfig.app.json` lists `types: ["vite/client", "vitest/globals"]`; adding `"node"` to reach
  `readFileSync` would let ordinary app code import a Node builtin and still typecheck — a far bigger
  hole than three sweeps are worth.

## What changed from earlier specs?

- **`protectedFolders.ts`** — `_config` added to `HIDDEN_BROWSER_FOLDERS` and
  `PICKER_LOCKED_FOLDERS`, in parity with `_directory` (SPEC-146). Both are bucket-root folders, so
  neither list can actually reach them; IAM is the mechanism and these are the belt-and-braces.
- **`lib/env.ts`** — `VITE_ENVIRONMENT` joins `OPTIONAL_ENV`. Optional because its degraded path is
  total: unset resolves the document's own `defaults` and still reports `'ready'`.
- **`ci.yml`** — `ruff check lambdas/` → `ruff check lambdas/ scripts/`, plus the validator step.
- **SPEC-146's `test_no_other_lambda_references_the_directory`** gained a second allowlist entry.
  `lambdas/test_feature_flags_config.py` names `_directory/usernames.json` to explain why the publish
  addresses one exact key and never syncs — the reasoning is the point, and the tripwire's real
  subject (a control plane treating the directory as an authorization input) is untouched.

## The accepted risk, stated plainly

**During an outage, a deliberate "off" does not take effect.** An unreadable, missing, unparseable or
wrong-version document resolves to the compiled-in defaults — everything on — and reports
`status: 'fallback'`. There is no banner and no toast: the user is not the audience for that failure.

Failing closed was the alternative and is worse: one S3 blip would strip the app to Files for
everyone. The cost is that the failure is **invisible from the app**, because every default is `true`
and a blocked read renders exactly like a healthy environment. That is what FR-009 exists for, and
why the live check below has to prove the document was *read* rather than that the app looks right.

**Turning a flag off changes no IAM grant, no queue permission and no credential scope.** A flag is
presentation. `featureFlags.service.test.ts` enumerates every `*.service.ts` under `features/` and
every module under `lib/` and fails if one imports the flags module — verified against a deliberate
violation, which the sweep named.

## Verification

Local, all green: `npm run lint`, `format:check`, `npm run build` (`tsc -b`), `npm run test:coverage`
(71 files / 1768 tests), `ruff check lambdas/ scripts/`, `mypy`, `pytest lambdas/` (2404 passed,
97.10%), `tofu validate` + `fmt -check`.

FR-008's three "already works" claims were **checked, not assumed**, and all three hold today: the
user-space bucket's `aws_s3_bucket_cors_configuration` allows `GET` from the app origin, its host is
in `csp_connect_src`, and the portal role is on the bucket policy's principal allowlist. FR-003's
deploy-role claim holds too (`s3:*` on `${user_space_bucket_arn}/*`), so no deploy-role statement was
added. Each is now a test rather than a belief.

**Help & guides: nothing to change.** No user-visible behaviour ships here — the resolved flag set is
read by nothing until SPEC-163, and documenting a feature that is not wired end to end is exactly
what SPEC-074 FR-005 forbids.

**Live check (OWED) — see `docs/testing/feature-flags-e2e.md`.** Publish the document, sign in, and
confirm in the network panel that the `GetObject` on `_config/feature-flags.json` returns **200** and
that the hook reports `'ready'`. A passing-looking app with `'fallback'` is a **failure** of this
spec. Confirm in the same pass that `_config/` is not listable from the file browser.
