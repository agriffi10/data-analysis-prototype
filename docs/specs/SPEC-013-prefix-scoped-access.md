# Spec: Prefix-Scoped S3 Access — Policy + File Browser Switchover

**ID:** SPEC-013
**Status:** Completed
**Last Updated:** 2026-06-12
**Depends On:** SPEC-010 (bucket), SPEC-011 (identity-tagged credentials), SPEC-012 (validated usernames)

> **Note:** Do not start this spec until SPEC-011's principal tag mapping is verified in CloudTrail — the policy below is a no-op (denies everything) without the `username` principal tag.

## Overview

Turn on real, isolated S3 access. A permission policy attached to the portal role grants each session access to exactly `dat-prod-user-space/{username}/*` — where `{username}` is the session's IAM principal tag, mapped server-side by the Identity Pool (SPEC-011), never asserted by the client. The file browser then switches from the SPEC-002 test bucket to the user-space bucket using the authenticated client from SPEC-011, rooted at the user's own prefix. After this spec, a signed-in user browses their own space and provably cannot touch anyone else's.

## Scope

### In Scope

- Permission policy on the portal role: object actions + scoped list, driven by `${aws:PrincipalTag/username}`
- Bucket policy on the user-space bucket restricting access to the portal role (+ account admin paths)
- File browser switchover: authenticated `getS3Client()` + `VITE_S3_USER_SPACE_BUCKET`, rooted at `{username}/`
- Removal of the SPEC-001/002 static-credential and anonymous client paths from the production flow (kept available behind a dev-only flag for local work without AWS)
- Negative-path verification (cross-user access denied) as an explicit checkpoint
- Deploy role permission expansion if any new IAM/S3 policy management actions are needed (likely covered by SPEC-010/012 — verify)

### Out of Scope

- Shared-space bucket access (Bucket 2 — model still TBD)
- Upload/download/delete UI (file browser remains read/list; mutations are a future spec — note FR-001 grants the actions so IAM is ready)
- `connections.json` handling (future Connection Manager spec)
- DO_NOT_DELETE marker (SPEC-014)

---

## Functional Requirements

### FR-001: Prefix-Scoped Permission Policy

#### Description:

The single policy statement pattern from `docs/architecture.md`, attached to the portal role.

#### Acceptance Criteria:

- [ ] Policy as `.tftpl` under `infra/modules/data/policies/`, attached to the SPEC-011 role
- [ ] Object actions (`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`) allowed only on `arn:aws:s3:::{bucket}/${aws:PrincipalTag/username}/*`
- [ ] `s3:ListBucket` allowed on the bucket ARN only with `s3:prefix` condition `["${aws:PrincipalTag/username}/", "${aws:PrincipalTag/username}/*"]`
- [ ] An explicit `Deny` statement for `s3:DeleteObject` on `arn:aws:s3:::{bucket}/*/DO_NOT_DELETE.txt` protects every user's prefix marker (SPEC-014) even from raw SDK calls; marker removal requires admin
- [ ] No statement grants anything when the `username` tag is absent (verify: a session without the tag gets implicit deny — the policy variable simply never matches)
- [ ] `tofu validate` + `deploy-infra.yml` PR plan pass

### FR-002: User-Space Bucket Policy

#### Description:

Defense in depth at the bucket: only the portal role (and break-glass admin) may use this bucket.

#### Acceptance Criteria:

- [ ] Bucket policy denies all S3 actions to principals other than the portal role and the account root (break-glass access is root-only — resolved 2026-06-10; the deploy role keeps bucket-*configuration* access via its identity policy, which the deny must not block for management actions)
- [ ] Deny statement uses `aws:PrincipalArn` conditions rather than relying on the absence of grants
- [ ] Applying the policy does not lock out the IaC itself (deploy role can still manage bucket configuration — test plan after apply)

### FR-003: File Browser Switchover

#### Description:

The browser now shows the authenticated user's own space.

#### Acceptance Criteria:

- [ ] `/files` uses `getS3Client()` (SPEC-011) and `VITE_S3_USER_SPACE_BUCKET`, with `rootPrefix = "{username}/"` derived from the authenticated user — reusing SPEC-002's root-prefix scoping so the UI never shows or escapes above the user's root
- [ ] The username segment is stripped from displayed paths/breadcrumbs (user sees `/documents/...`, not `/alice/documents/...`)
- [ ] An empty prefix renders the existing empty state (no error) — a brand-new user sees an empty browser
- [ ] Credential expiry mid-session triggers one transparent retry via `getS3Client(true)` before surfacing an error
- [ ] `VITE_S3_BUCKET_NAME`/static-credential path no longer reachable in a production build; local-dev fallback documented in `.env.example`
- [ ] All existing FileBrowser tests updated/passing; new tests cover prefix derivation and the retry path

### FR-004: Isolation Verification

#### Description:

The core security property is proven, not assumed.

#### Acceptance Criteria:

- [ ] With two test users (alice, bob): alice uploads via CLI to `alice/`, signs in and sees it; alice's session, via hand-crafted SDK call (dev console) against `bob/`, receives `AccessDenied` for Get, Put, and List
- [ ] A raw `ListObjectsV2` on the bucket root (no prefix) with alice's credentials is denied
- [ ] These steps are appended to `docs/testing/e2e.md` (SPEC-009) as the isolation section, executed and dated

---

## Data Model

No new types. `FileBrowser` props unchanged (`bucket`, `prefix`, `rootPrefix`).

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts — now takes the client
// from getS3Client() instead of module-level static client
listObjects(params: { bucket: string; prefix: string }): Promise<ServiceResult<ListResult>>;
```

## Environment Variables

`VITE_S3_USER_SPACE_BUCKET` becomes required in production builds (add to GitHub Actions variables; extend `.github/workflows/README.md`). `VITE_S3_BUCKET_NAME` demoted to local-dev-only in `.env.example`.

## File & Folder Structure

```
infra/modules/data/
├── iam.tf                      ← + policy attachment
├── s3.tf                       ← + bucket policy
└── policies/
    ├── portal-role-permissions.json.tftpl   ← NEW
    └── user-space-bucket-policy.json.tftpl  ← NEW

apps/portal/src/
├── features/file-browser/      ← service reworked to authenticated client
└── routes/FilesPage.tsx        ← user-space bucket + {username}/ root
```

## Implementation Phases

### Phase 1: IaC — role policy + bucket policy

- FR-001, FR-002

#### Checkpoint

After apply: CLI-simulated check with `aws iam simulate-principal-policy` (or a real STS session from the app) confirms object access allowed under own prefix, denied elsewhere. Deploy role still manages the bucket (run a no-op plan).

### Phase 2: App switchover + isolation proof

- FR-003, FR-004

#### Checkpoint

Full pass: sign in → see own files → cross-user attempts denied (FR-004 executed and recorded in `docs/testing/e2e.md`). `npm run test`, `npm run lint` pass. Deployed CloudFront app works end to end with a real user.

## Open Questions

- [x] **Resolved (2026-06-10):** `s3:DeleteObject` is granted now (IAM ready; UI is the gate) — except the marker deny in FR-001.
- [x] **Resolved (2026-06-10):** break-glass is account root only; no named admin role in the bucket policy.
