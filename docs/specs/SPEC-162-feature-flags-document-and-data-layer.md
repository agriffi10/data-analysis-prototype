# Spec: Feature Flags — Document, Publish Pipeline & Browser Data Layer

**ID:** SPEC-162
**Status:** Draft
**Last Updated:** 2026-08-10
**Depends On:** SPEC-146/147 (the advisory-document precedent), SPEC-155 (`lib/s3Json.ts` `readJsonDocument`), SPEC-138 (a bad gate value is a hard error)

## Overview

The portal ships every feature to every environment the moment it merges. There is no way to hold a
half-finished area back from users, or to run an environment with a feature deliberately off. This
spec adds a **feature-flag document**: a git-controlled JSON file, uploaded to the admin bucket by
CI, that names each primary feature — Files, Query, Shared Workspaces, Data Quality — as on or off,
**per environment**, so one environment can hide Query while another keeps it.

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
- A **publish workflow** that validates the document and uploads it to each environment's admin
  bucket at `config/feature-flags.json` with `Cache-Control: no-cache`.
- **Validation as a hard error**, in CI on every PR and again before upload: unknown flag keys,
  non-boolean values, an unknown `version`, or an environment key with no upload target all fail the
  job.
- The browser data layer: `featureFlags.service.ts`, `useFeatureFlags()`, the resolution rules, and
  the compiled-in defaults.
- Two new `VITE_*` variables (`VITE_ENVIRONMENT`, `VITE_S3_ADMIN_BUCKET`) **including their deploy
  wiring** — `deploy-app.yml` build env plus the GitHub Actions repo variables.
- Portal-role IAM: `s3:GetObject` on exactly `{admin_bucket}/config/feature-flags.json`.
- Deploy-role IAM: `s3:PutObject` on exactly that key.
- **The two infra gates that make the browser read possible at all** (FR-008): a CORS configuration
  on the admin bucket, and the admin bucket's host added to the CloudFront CSP `connect-src`.

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

A workflow uploads the validated document to each environment's admin bucket, independently of an
app build — flipping a flag must not require rebuilding and redeploying the SPA.

#### Acceptance Criteria:

- [ ] The workflow runs on pushes to `main` that touch `config/**`, and on manual dispatch.
- [ ] It uploads to `s3://{admin_bucket}/config/feature-flags.json` for every declared environment,
      with `Cache-Control: no-cache` so a flag change is picked up on the next fetch.
- [ ] The upload uses the existing GitHub-OIDC deploy role; the deploy role's policy grants
      `s3:PutObject` on **exactly that key**, not the prefix or the bucket.
- [ ] A failed validation stops the workflow before any upload.
- [ ] The workflow is watched to completion like every other deploy — a red publish is a red deploy.

### FR-004: Reading the document in the browser

#### Description:

The app fetches the document once per session through the shared JSON reader and exposes a resolved
flag set.

#### Acceptance Criteria:

- [ ] `getFeatureFlags()` reads `config/feature-flags.json` from `VITE_S3_ADMIN_BUCKET` through
      `readJsonDocument`, returns `ServiceResult<FeatureFlags>` and never throws.
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

- [ ] `VITE_ENVIRONMENT` and `VITE_S3_ADMIN_BUCKET` are documented in `apps/portal/.env.example` with
      their source.
- [ ] Both are added to `deploy-app.yml`'s build env **and** set as GitHub Actions repo variables.
- [ ] A missing `VITE_ENVIRONMENT` resolves to `defaults` rather than crashing, and a missing
      `VITE_S3_ADMIN_BUCKET` resolves to the compiled-in fallback — the app never white-screens on an
      unwired variable.

### FR-008: The admin bucket must actually be reachable from the browser

#### Description:

The IAM grant is necessary and **not sufficient**. The admin bucket has never been read by a browser
and two independent gates block it — neither of which the IAM policy can affect:

1. **No CORS.** `infra/modules/analytics/s3.tf` deliberately carries no
   `aws_s3_bucket_cors_configuration`, with a comment saying the bucket is never read by the
   browser. The user-space and shared-space buckets both have one — which is why SPEC-146's
   directory read works, and why this spec's stated precedent does not transfer: that document
   lives in the user-space bucket.
2. **Not in the enforcing CSP.** `csp_connect_src` enumerates exactly two S3 hosts (user-space and
   shared-space). The admin bucket is a third. `connect-src` **is** the app's network surface, and
   the recorded consequence of omitting a host is SPEC-140's Hosted UI domain breaking fresh sign-in
   for a day.

Left unfixed, the fetch is blocked, FR-005's silent fallback makes the app look completely normal
with every flag on, and SPEC-163 then ships a gating system that can never gate anything.

#### Acceptance Criteria:

- [ ] An `aws_s3_bucket_cors_configuration` on the admin bucket allows `GET` from the app origin,
      scoped no wider than the existing data-bucket configurations; the "never read by the browser"
      comment is replaced, not left contradicting the code.
- [ ] The admin bucket's S3 host is added to `csp_connect_src`, threaded through a
      `modules/app` variable from root locals — **variables, never module outputs** (SPEC-140's rule).
- [ ] A browser fetch of `config/feature-flags.json` succeeds from the deployed app with **no** CSP
      violation and **no** CORS error in the console.
- [ ] The verification uses a **same-origin page script**, not a CDP eval — a CDP eval bypasses page
      CSP and would pass against a policy that blocks the real app (SPEC-140's settled method).
- [ ] Findings are diffed per check ID, not by total.

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
# Admin bucket holding config/feature-flags.json. Source: `tofu output` → athena admin bucket name.
VITE_S3_ADMIN_BUCKET=dat-prod-athena-admin
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

### Phase 2: Publish pipeline + IAM + reachability

- `deploy-config.yml`; deploy-role `PutObject` and portal-role `GetObject`, each scoped to the exact
  key; `tofu validate` + policy render checks. **Note:** this is the portal role's first grant on the
  admin bucket — keep it to one object, no `ListBucket`, no prefix wildcard.
- **FR-008's two gates in the same phase as the grant** — the CORS configuration and the
  `connect-src` host. An IAM grant landed without them is a grant that cannot be exercised, and the
  silent fallback means nothing downstream will report it.

### Phase 3: Browser data layer

- Service, hook, defaults, resolution and fallback; the FR-006 tripwire test; `.env.example` and
  `deploy-app.yml` wiring.

### Phase 4: Verification

- Unit tests across every fallback path.
- **Live check (owed):** publish the document, sign in, and confirm in the network panel that the
  `GetObject` on `config/feature-flags.json` **returns 200** and that the hook reports `'ready'`,
  not `'fallback'` — the IAM grant, the CORS configuration and the CSP entry are each only proven by
  a real fetch, and all three must hold for one to matter. Check the console for CSP and CORS
  violations explicitly; a working-looking app proves nothing here.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, a `component-inventory/feature-flags-feature.md` area file plus a
  router row (a whole new area), a `decisions.md` entry (flags are presentation-only; the portal
  role's first admin-bucket read and why it is scoped to one key), and one Key Decisions line.
  **No Help & guides change** — nothing user-visible ships until SPEC-163.
