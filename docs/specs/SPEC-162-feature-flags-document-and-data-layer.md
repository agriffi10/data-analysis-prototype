# Spec: Feature Flags — Document, Publish Pipeline & Browser Data Layer

**ID:** SPEC-162
**Status:** Draft
**Last Updated:** 2026-08-10
**Depends On:** SPEC-146/147 (the advisory-document precedent), SPEC-155 (`lib/s3Json.ts` `readJsonDocument`), SPEC-138 (a bad gate value is a hard error)

## Overview

The portal ships every feature to every environment the moment it merges. There is no way to hold a
half-finished area back from users, or to run an environment with a feature deliberately off. This
spec adds a **feature-flag document**: a git-controlled JSON file, published by CI to
`_config/feature-flags.json` in the **user-space bucket**, that names each primary feature — Files,
Query, Shared Workspaces, Data Quality — as on or off, **per environment**, so one environment can
hide Query while another keeps it.

**It sits beside `_directory/usernames.json` deliberately.** That bucket already has a CORS
configuration, its host is already in the enforcing CSP `connect-src`, the portal role already has a
one-line `GetObject` grant on `_directory/*` to copy, and the deploy role already holds
`${user_space_bucket_arn}/*`. The admin bucket has **none** of those: it carries an explicit "never
read by the browser" comment in place of a CORS config, and adding it to `connect-src` is the exact
shape of the omission that broke fresh sign-in for a day (SPEC-140). Putting an advisory,
browser-read document in the bucket that already serves one costs nothing and adds no new exposure.

This spec builds the document, the publish pipeline, and the browser data layer that resolves it.
SPEC-163 uses the result to actually hide things.

**A flag is presentation, never authorization.** Turning Query off hides the tab and the entry
points; it does not revoke a single IAM grant, and the Athena permissions on the portal role are
untouched. Anyone who reads the flag document as a security boundary has misread it — the same rule
SPEC-146 wrote for the username directory ("advisory, never an authorization input"), and this spec
pins it with a test.

## Scope

### In Scope

- `config/feature-flags.json` in the repository — the **only** place a flag is edited.
- A **publish workflow** that validates the document and uploads it to each environment's user-space
  bucket at `_config/feature-flags.json` with `Cache-Control: no-cache`.
- **Validation as a hard error**, in CI on every PR and again before upload: unknown flag keys,
  non-boolean values, an unknown `version`, or an environment key with no upload target all fail the
  job.
- The browser data layer: `featureFlags.service.ts`, `useFeatureFlags()`, the resolution rules, and
  the compiled-in defaults.
- **One** new `VITE_*` variable (`VITE_ENVIRONMENT`) **including its deploy wiring** —
  `deploy-app.yml` build env plus the GitHub Actions repo variable. The bucket is resolved from the
  existing `userSpaceBucket()` helper, so no bucket variable is added.
- Portal-role IAM: `s3:GetObject` on `{user_space_bucket}/_config/*`, a `ReadTheFeatureFlags` Sid
  written directly beside the existing `ReadTheUsernameDirectory`.
- **No deploy-role change** — the deploy role already holds `${user_space_bucket_arn}/*`. FR-003
  asserts this rather than assuming it.
- **No CORS, CSP, or bucket-policy change** — all three already cover this bucket. FR-008 asserts
  that too, because "it already works" is a claim, not a fact, until something checks it.

### Out of Scope

- **Hiding anything.** No nav, route or button changes here — SPEC-163. This spec ships a resolved
  flag set that nothing reads yet.
- Per-user, per-group or percentage rollout. Flags are per **environment**, full stop.
- Runtime flag flipping from inside the app, or any admin UI (out of scope repo-wide).
- Flags for anything below a primary feature (individual dialogs, sub-features). Four flags, named
  for the four features the user named.
- Using a flag to gate an IAM grant, a service call's authorization, or a control-plane decision —
  explicitly forbidden, and FR-006 tests for it.

---

## Functional Requirements

### FR-001: The document

#### Description:

One JSON file in git describes every flag, a `defaults` block, and per-environment overrides.

#### Acceptance Criteria:

- [ ] `config/feature-flags.json` exists with `version`, `defaults` (all four flags, explicit
      booleans) and `environments` (a map of environment name → partial override).
- [ ] The four flag keys are exactly `files`, `query`, `sharedWorkspaces`, `dataQuality`.
- [ ] An environment block may set any subset of flags; anything it omits comes from `defaults`.
- [ ] The file is the single edit point — no flag value is duplicated in `.env`, Terraform, or a
      workflow.

### FR-002: Validation is a hard error

#### Description:

A malformed document must never reach a bucket. It is validated in CI on every pull request and
again in the publish workflow immediately before upload.

#### Acceptance Criteria:

- [ ] An unknown key in `defaults` or in any environment block **fails** the job (a typo'd flag must
      not silently do nothing).
- [ ] A non-boolean flag value fails the job.
- [ ] A `version` the validator does not know fails the job.
- [ ] An environment key in the document with **no** corresponding upload target — and an upload
      target with no environment key — both fail the job. A block that is never published, and a
      target that publishes nothing, are both defects rather than defaults.
- [ ] `defaults` missing any of the four flags fails the job.
- [ ] The validator is exercised by its own tests, including a guard-the-guard case proving it fails
      on a document it should reject (SPEC-153's discipline).

### FR-003: The publish pipeline

#### Description:

A workflow uploads the validated document to each environment's user-space bucket, independently of
an app build — flipping a flag must not require rebuilding and redeploying the SPA.

#### Acceptance Criteria:

- [ ] The workflow runs on pushes to `main` that touch `config/**`, and on manual dispatch.
- [ ] It uploads to `s3://{user_space_bucket}/_config/feature-flags.json` for every declared
      environment, with `Cache-Control: no-cache` so a flag change is picked up on the next fetch.
- [ ] The upload uses the existing GitHub-OIDC deploy role, whose policy **already** covers
      `${user_space_bucket_arn}/*` — the spec asserts this and adds **no** deploy-role statement. If
      the assertion fails, that is the finding, not a licence to widen the grant.
- [ ] The upload never touches `_directory/` — a mis-scoped `--delete` or a wrong key that clobbered
      the username directory would break typeahead everywhere. The workflow addresses one exact key
      and performs no sync or delete.
- [ ] A failed validation stops the workflow before any upload.
- [ ] The workflow is watched to completion like every other deploy — a red publish is a red deploy.

### FR-004: Reading the document in the browser

#### Description:

The app fetches the document once per session through the shared JSON reader and exposes a resolved
flag set.

#### Acceptance Criteria:

- [ ] `getFeatureFlags()` reads `_config/feature-flags.json` from `userSpaceBucket()` through
      `readJsonDocument`, returns `ServiceResult<FeatureFlags>` and never throws — the same service
      shape as `getUserDirectory()`, one prefix over.
- [ ] `useFeatureFlags()` exposes `{flags, status}` with `status: 'loading' | 'ready' | 'fallback'`,
      is gated on a signed-in user, and uses a long `staleTime` with `retry: false` — the same shape
      as `useUserDirectory`.
- [ ] The resolved set is `defaults` merged with `environments[VITE_ENVIRONMENT]`; an environment
      the document does not name resolves to `defaults` and reports `'ready'`, not an error.
- [ ] The hook's `flags` object always holds all four keys as booleans, whatever the document said —
      no consumer ever handles `undefined`.

### FR-005: Fallback behaviour

#### Description:

The app must not become unusable because a presentation file could not be read.

#### Acceptance Criteria:

- [ ] A fetch failure, a missing object, unparseable JSON, or an unsupported `version` all resolve to
      the **compiled-in defaults** and report `status: 'fallback'`.
- [ ] A *single* malformed value (a flag set to `"true"` rather than `true`) falls back **for that
      key only**; the rest of the document is honoured.
- [ ] The compiled-in defaults live in one exported constant with every flag `true`, and a test
      asserts they match `config/feature-flags.json`'s `defaults` block — the file and the fallback
      cannot drift apart silently.
- [ ] The fallback is recorded in the spec's delivery doc as the accepted risk it is: **during an
      outage, a deliberate "off" does not take effect.** No banner, no toast — the user is not the
      audience for that failure.
- [ ] Nothing about the failure is surfaced as a user-facing error.

### FR-006: A flag is never an authorization input

#### Description:

The boundary that keeps this feature honest.

#### Acceptance Criteria:

- [ ] No service function, no request builder and no IAM policy branches on a flag value; a test
      enumerates `src/features/**/*.service.ts` and `src/lib/**` and fails if any imports the flags
      module.
- [ ] Turning a flag off changes **no** IAM grant, queue permission or credential scope, and the
      delivery doc says so in one line.
- [ ] The flags module carries a docstring stating the rule, in the same terms as the user
      directory's advisory note.

### FR-007: Deploy wiring for the new variables

#### Description:

The recorded `VITE_*` trap: a variable the app reads that is not wired into the deploy ships
`undefined` in production.

#### Acceptance Criteria:

- [ ] `VITE_ENVIRONMENT` is documented in `apps/portal/.env.example` with its source.
- [ ] It is added to `deploy-app.yml`'s build env **and** set as a GitHub Actions repo variable.
- [ ] A missing `VITE_ENVIRONMENT` resolves to `defaults` rather than crashing — the app never
      white-screens on an unwired variable.
- [ ] **No bucket variable is added.** The bucket comes from the existing `userSpaceBucket()` helper, which
      the file browser and the username directory already resolve through, so there is no second
      place for the bucket name to be wrong.

### FR-008: The reachability assumptions are asserted, not assumed

#### Description:

Moving the document to the user-space bucket means CORS, the CSP `connect-src` entry and the bucket
policy are all **already** in place — that is the whole reason for the location. But "already works"
is a claim about three files this spec does not touch, and a claim nothing checks is how a
silent-fallback feature ships permanently broken. Each gets one assertion.

#### Acceptance Criteria:

- [ ] A test or plan assertion confirms the user-space bucket has an
      `aws_s3_bucket_cors_configuration` allowing `GET` from the app origin; if it is ever removed,
      this spec's feature breaks and the assertion is what says so.
- [ ] A test or plan assertion confirms the user-space bucket host is present in `csp_connect_src`.
- [ ] A rendered-policy assertion confirms the portal role is on the user-space bucket-policy
      principal allowlist, so the identity grant is not overridden by a resource Deny. It is the
      first entry today — the assertion exists so a later edit to that hand-maintained list fails a
      test rather than silently killing this feature into its all-on fallback.
- [ ] **No new CORS resource, no new `connect-src` host, and no bucket-policy change is made.** If
      any of the three assertions fails, that is a finding to raise — not a licence to widen infra
      inside this spec.

### FR-009: A silent fallback must not hide a broken read

#### Description:

FR-005 is deliberately quiet, which means a permanently-blocked fetch is indistinguishable from a
healthy all-on environment. The live check has to prove the document was **read**, not that the app
looks right.

#### Acceptance Criteria:

- [ ] The live check confirms a successful `GetObject` response for the document in the network
      panel — a passing app with `status: 'fallback'` is a **failure** of this spec, not a pass.
- [ ] A development-only diagnostic (console debug or a dev-build-only indicator) distinguishes
      `'ready'` from `'fallback'`; it is stripped from production builds and is never a user-facing
      banner.
- [ ] The delivery doc records which status the live check observed.

---

## Data Model

```jsonc
// config/feature-flags.json
{
  "version": 1,
  "defaults": {
    "files": true,
    "query": true,
    "sharedWorkspaces": true,
    "dataQuality": true
  },
  "environments": {
    "prod": {}
  }
}
```

```ts
// src/features/feature-flags/featureFlags.types.ts

export type FeatureFlagKey = 'files' | 'query' | 'sharedWorkspaces' | 'dataQuality';

export type FeatureFlags = Record<FeatureFlagKey, boolean>;

/** `'fallback'` = the compiled-in defaults are in force because the document was unusable. */
export type FeatureFlagsStatus = 'loading' | 'ready' | 'fallback';

export type FeatureFlagDocument = {
  version: number;
  defaults: FeatureFlags;
  environments: Record<string, Partial<FeatureFlags>>;
};
```

## API / Interface Contract

```ts
getFeatureFlags(environment: string): Promise<ServiceResult<FeatureFlags>>;

useFeatureFlags(): {flags: FeatureFlags; status: FeatureFlagsStatus};
```

## Environment Variables

Add to `apps/portal/.env.example`:
```
# Which feature-flag environment block this build resolves (SPEC-162).
VITE_ENVIRONMENT=prod
# (No bucket variable — the document lives in the user-space bucket, resolved via userSpaceBucket().)
```

## File & Folder Structure

```
config/
└── feature-flags.json
.github/workflows/
└── deploy-config.yml
apps/portal/src/features/feature-flags/
├── featureFlags.service.ts
├── featureFlags.service.test.ts
├── featureFlags.types.ts
├── featureFlagDefaults.ts
├── featureFlagKeys.ts
├── useFeatureFlags.ts
├── useFeatureFlags.test.ts
└── index.ts
```

## Implementation Phases

### Phase 1: Document + validator

- The JSON file, the validator, its tests (including guard-the-guard), and the CI job on PRs.

### Phase 2: Publish pipeline + IAM

- `deploy-config.yml`; the portal-role `ReadTheFeatureFlags` Sid on `_config/*`, written beside
  `ReadTheUsernameDirectory`; `tofu validate` + policy render checks. **No `ListBucket` widening** —
  the document must stay invisible to the file browser. IAM already guarantees it (`UserPrefixList`
  conditions `s3:prefix` on the username, and `_config` is not a claimable username), but
  `_directory` **also** appears in `HIDDEN_BROWSER_FOLDERS` and `PICKER_LOCKED_FOLDERS` as
  deliberate belt-and-braces — so `_config` joins both lists too. Parity with the directory means
  both layers, not just the IAM one.
- FR-008's three assertions (CORS, `connect-src`, bucket-policy allowlist) land here too, as checks
  on infra this spec does not change.

### Phase 3: Browser data layer

- Service, hook, defaults, resolution and fallback; the FR-006 tripwire test; `.env.example` and
  `deploy-app.yml` wiring.

### Phase 4: Verification

- Unit tests across every fallback path.
- **Live check (owed):** publish the document, sign in, and confirm in the network panel that the
  `GetObject` on `_config/feature-flags.json` **returns 200** and that the hook reports `'ready'`,
  not `'fallback'`. The silent fallback means a working-looking app proves nothing — an all-on
  environment is exactly what a permanently blocked read produces. Confirm the document is not
  listable from the file browser in the same pass.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, a `component-inventory/feature-flags-feature.md` area file plus a
  router row (a whole new area), a `decisions.md` entry (flags are presentation-only; and why the
  document lives beside `_directory/` rather than in the admin bucket — the second advisory
  browser-read document in that bucket, and the precedent for a third), and one Key Decisions line.
  **No Help & guides change** — nothing user-visible ships until SPEC-163.
