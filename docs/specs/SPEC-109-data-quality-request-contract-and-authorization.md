# Spec: Data Quality — Request Contract, Browser Enqueue & `validate-authorize`

**ID:** SPEC-109
**Status:** Completed
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-108 (data-quality foundation), SPEC-056 (shared-space access model), SPEC-011 (Cognito identity)

> **Read `docs/data-quality-architecture.md` §2.3, §3 and §7 first.**

## Overview

Define the **request envelope** a browser sends to start a quality check, grant the portal role permission to send it, and implement the first verb: **`validate-authorize`**, which verifies the caller's Cognito ID token server-side, derives the actor from the verified claim, and authorizes read access to the requested location. This spec also gives the shared execution role its **S3 grants** — and the explicit **`Deny`** that stops any bug in this pipeline from permanently destroying a user's notification inbox.

Two details are requirements, not preferences, because getting either wrong fails silently:

**The `MessageGroupId` must be a hash.** SQS caps it at **128 characters**; S3 keys reach 1024. A raw bucket-plus-prefix group id fails the send **in the browser**, for exactly the users with the deepest folder structures. Every existing producer gets away with a raw id only because it uses a bounded catalog identifier (`tableBuild.service.ts:50` uses `space.database`, ≤63 chars by `CATALOG_IDENTIFIER_RE`).

**The execution role needs `s3:GetObject` on the report prefix, not just `PutObject`.** `assemble-report` (SPEC-112) reads back the intermediate results it wrote. A write-only grant would fail at the last verb, after all the work was done.

## Scope

### In Scope

- The **request envelope** (`requestId`, `idToken`, `space`, `location`) and its TypeScript type.
- The SPA **enqueue service** (`dataQuality.service.ts` → `enqueueQualityCheck`), with the **SHA-256 hashed `MessageGroupId`** and `MessageDeduplicationId = requestId`.
- **Portal-role IAM**: `sqs:SendMessage` on the data-quality request queue **only**.
- `VITE_DATA_QUALITY_QUEUE_URL` — wired through **all four** points, including the manual GitHub repo variable.
- The **`validate-authorize`** Lambda: ID-token verification (`cpcommon.auth`), actor derivation, personal/shared authorization, location normalization, report-destination validation.
- The **execution role's S3 grants**: read on the source location, **read + write** on the report prefix — plus an explicit **`Deny s3:PutObject`** on `*/user_settings/*` and `*/DO_NOT_DELETE.txt` across both buckets.
- The SFN `ValidateAuthorize` state wired to the real Lambda, with its `Catch` → cleanup → failure path.

### Out of Scope

- Listing, DDL, the profile query, the byte scan, report assembly — SPEC-110→112.
- The **Glue / Athena / Lake Formation** grants — SPEC-111, the spec that first needs them.
- The UI — SPEC-113. This spec's deliverable is a unit-tested service; SPEC-113 is its first caller.
- Notifications — SPEC-114.

---

## Functional Requirements

### FR-001: The request envelope

#### Description

One envelope, minted in the browser, carrying everything the pipeline needs and nothing it can spoof.

#### Acceptance Criteria:

- [ ] The envelope is `{ requestId, idToken, space: { kind, bucket, prefix }, location }`, `kind` being `'personal' | 'shared'`.
- [ ] `requestId` is a browser-minted UUIDv4, present on **every** request. SPEC-112 keys the report and the manifest on it; SPEC-114 builds the notification dedup id from it. A request without one — or any malformed envelope — is a terminal **`invalid_request`**, a code registered in SPEC-114 FR-002's set.
- [ ] The envelope carries **no actor or username field** — the actor is derived server-side from the verified token claim, never from the body.
- [ ] The type lives at `apps/portal/src/features/data-quality/dataQuality.types.ts`.

### FR-002: The enqueue service, with a hashed `MessageGroupId`

#### Acceptance Criteria:

- [ ] `MessageGroupId` = the **SHA-256 hex digest** (exactly 64 characters) of the canonical target location `{bucket}/{normalizedLocation}`, computed with `crypto.subtle.digest` — the primitive already used at `tableShare.service.ts:22-30`.
- [ ] `MessageGroupId` is **never** the raw location. A test constructs a location whose raw form is **over 128 characters**, asserts the resulting group id is exactly 64 characters, and asserts the send succeeds.
- [ ] A rationale comment records the failure this prevents: SQS's 128-character `MessageGroupId` cap versus S3's 1024-character keys, failing the send in the browser.
- [ ] Two checks of the **same** location produce the **same** group id (they serialize); two different locations produce different group ids (they run in parallel). Both asserted.

  > **SUPERSEDED 2026-09-15.** One group id orders the starts, not the runs: the Pipe is `FIRE_AND_FORGET`, so two same-location checks run at once, harmlessly, since every per-run key is the request id — `docs/decisions/control-planes.md`, *A group id orders the STARTS, not the runs*. The "same-location-serializes case" below tests the same group id and nothing more.
- [ ] `MessageDeduplicationId` = `requestId`.
- [ ] The service returns a `ServiceResult<T>` and never throws, per CLAUDE.md's service convention.

### FR-003: Portal-role grant + the env var (all four wiring points)

#### Acceptance Criteria:

- [ ] The portal role gains `sqs:SendMessage` on the data-quality request queue ARN **only** — no other queue, no other action. Delivered as a small `.tftpl` attached **by name** to the shared portal role, following `infra/modules/table-share/policies/portal-role-table-share.json.tftpl`.
- [ ] `VITE_DATA_QUALITY_QUEUE_URL` is added to: (1) the module's `outputs.tf`, (2) `apps/portal/.env.example` with a description, (3) `deploy-app.yml`'s build env, **and (4) set as a GitHub Actions repo variable**.
- [ ] The PR description explicitly confirms step (4) was done. Missing it ships production with the var `undefined`, and correct IAM will not save it — the documented "VITE_* deploy gotcha" (`apps/portal/.env.example:61-62`).

### FR-004: `validate-authorize` — identity

#### Acceptance Criteria:

- [ ] The Lambda verifies the ID token via `cpcommon.auth` (offline JWKS, RS256, `exp`/`iss`/`aud` required, `token_use == "id"`) and derives the actor from the `cognito:username` claim.
- [ ] A missing, malformed, expired, wrong-audience, or non-ID token is a terminal `unauthorized`.
- [ ] The actor is **never** read from the message body.
- [ ] Event-shape validation uses `cpcommon.events` and yields a typed terminal **`invalid_request`** (FR-001), not a bare `KeyError` (per SPEC-083).

### FR-005: `validate-authorize` — authorization and location safety

#### Acceptance Criteria:

- [ ] **Personal:** the space bucket must be the user-space bucket and the normalized location must start with `{actor}/`. Anything else is a terminal `forbidden` ("location escapes the personal space").
- [ ] **Shared:** the registry record for the space must have `status == "active"` **and** the actor must be in `members` (`cpcommon.registry.is_active_member`); the bucket must be the shared-space bucket; the location must start with `{spaceName}/`.
- [ ] The check is on the **space's** provisioning status, **not** SPEC-073's per-member Pending/Active join chip. **A Pending member passes** — SPEC-073 is explicit that access is granted at add time. A test asserts a Pending member is authorized, so that nobody "fixes" this later.
- [ ] Path traversal is neutralized: the location is normalized before comparison, and `..` segments cannot escape the space prefix. A traversal attempt is a terminal `forbidden`.
- [ ] The **report destination** (`{space}/_data-quality-reports/{requestId}/`) is validated to resolve inside the same space and not to collide with a reserved prefix (`athenaresults/`, `user_settings/`, `shared_tables/`, `_fc-work/` — the file-converter arc's scratch prefix, included defensively — or the root `DO_NOT_DELETE.txt`). The list is a **`dqcommon.config` constant**; the file-converter arc keeps a matching constant (SPEC-116's reserved-prefix blocklist), and a comment in each points at the other so the two lists cannot drift apart.
- [ ] Every failure is terminal with a **friendly** reason from `cpcommon.messages` (SPEC-106) — never raw AWS text.

### FR-006: The execution role's S3 grants — and the `Deny` that makes them safe

#### Description

This is the spec that first lets the pipeline touch S3, so it is the spec that must make it safe. Scoping the role to "the actor's space" is **not sufficient**.

#### Acceptance Criteria:

- [ ] The role gains `s3:GetObject` + `s3:ListBucket` scoped to the source location in both buckets.
- [ ] The role gains **`s3:PutObject` AND `s3:GetObject`** on the report prefix (`_data-quality-reports/`). A comment records why the read matters: `assemble-report` (SPEC-112) reads back the intermediate results it wrote, and a write-only grant would fail at the final verb after all the work was done.
- [ ] The role carries an explicit **`Deny s3:PutObject`** on `*/user_settings/*` and `*/DO_NOT_DELETE.txt` in **both** buckets — the cross-bucket deny at `infra/modules/table-share/policies/execution.json.tftpl:59-68` is the shape to copy.
- [ ] A comment records the disaster this prevents: the user-space policy denies `s3:DeleteObject` on `user_settings/*` (`analytics/policies/portal-role-analytics.json.tftpl:67-72`) but leaves `s3:PutObject` **wide open**, so any space-scoped writer can overwrite `notifications.json` and **permanently destroy the notification inbox — the user cannot even delete the corrupt file to recover.** The `Deny` is what makes the guarantee; FR-005's destination validation is defence in depth.
- [ ] `s3:DeleteObject` is granted nowhere in this arc.
- [ ] The role gains **no** Glue, Athena, or Lake Formation permission in this spec. A plan assertion confirms the rendered policy contains no `glue:`, `athena:`, or `lakeformation:` action.

---

## Data Model

```ts
// apps/portal/src/features/data-quality/dataQuality.types.ts

export type DataQualitySpaceKind = 'personal' | 'shared';

export type DataQualitySpace = {
  kind: DataQualitySpaceKind;
  bucket: string;
  /** The space root prefix: `{username}/` or `{spaceName}/`. */
  prefix: string;
};

export type DataQualityRequest = {
  /** UUIDv4, browser-minted. Keys the manifest, the intermediate results, and the report. */
  requestId: string;
  space: DataQualitySpace;
  /** The file or folder key to check, relative to the bucket. */
  location: string;
};

/** The wire envelope — `idToken` is attached at send time, never stored. */
export type DataQualityMessage = DataQualityRequest & { idToken: string };
```

## API / Interface Contract

```ts
// apps/portal/src/features/data-quality/dataQuality.service.ts

enqueueQualityCheck(req: DataQualityRequest): Promise<ServiceResult<{ requestId: string }>>;

// MessageGroupId         = sha256Hex(`${req.space.bucket}/${normalize(req.location)}`)   // 64 chars, ALWAYS
// MessageDeduplicationId = req.requestId
```

## Environment Variables

Add to `apps/portal/.env.example`:
```
# SPEC-109: the data-quality request queue (name pinned in SPEC-108 FR-001).
# NOTE: wire this into deploy-app.yml's build env AND set the GitHub repo variable,
# or production ships it undefined (the VITE_* deploy gotcha).
VITE_DATA_QUALITY_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account>/<project>-prod-data-quality-requests.fifo
```

## File & Folder Structure

```
apps/portal/src/features/data-quality/
├── dataQuality.types.ts
├── dataQuality.service.ts
├── dataQuality.service.test.ts
└── index.ts
lambdas/data-quality-validate-authorize/validate_authorize.py    (+ tests)
infra/modules/data-quality/policies/execution.json.tftpl          # S3 grants + the Deny
infra/modules/data-quality/policies/portal-role-data-quality.json.tftpl
infra/modules/data-quality/state-machine.asl.json.tftpl           # ValidateAuthorize → real Lambda
```

## Implementation Phases

### Phase 1: Contract + enqueue service

- Types; the service with the **hashed** group id; unit tests covering the over-128-character location, the same-location-serializes case, and the different-locations-parallelize case.

### Phase 2: `validate-authorize`

- Identity (FR-004); authorization, location normalization and destination validation (FR-005); typed terminals with friendly reasons.
- Tests: valid personal; valid shared (active member); **valid shared (Pending member — must pass)**; non-member; wrong bucket; traversal attempt; expired token; an access token supplied instead of an ID token.

### Phase 3: IAM + wiring + SFN state

- Portal-role grant; execution-role S3 grants **and the `Deny`** (FR-006); the four `VITE_*` wiring points including the manual repo variable; wire the SFN `ValidateAuthorize` state to the real Lambda with its `Catch` → cleanup → failure path. Completion ritual.
