# Spec: User-Space Bucket IaC — `data` Module

**ID:** SPEC-010
**Status:** Draft
**Last Updated:** 2026-06-10
**Depends On:** SPEC-003 (IaC project), SPEC-005 (deploy-infra workflow)

## Overview

Provision Bucket 1 — the user-space S3 bucket where each user's files live under their own username prefix — in a new bounded-context module `infra/modules/data/`. This is pure infrastructure: the bucket, its CORS configuration for browser SDK access, and the deploy role permissions needed to manage it. No IAM access policies for users are created here (SPEC-011/013) and no application code changes. This bucket is the foundation for the entire SPEC-010→014 data-access arc.

## Scope

### In Scope

- New `infra/modules/data/` module
- User-space S3 bucket (`{project_name}-prod-user-space`, e.g. `dat-prod-user-space`), private, all public access blocked
- CORS configuration for browser SDK calls (localhost + deployed app URL origins)
- Bucket-level hygiene: SSE-S3 encryption, ownership controls (`BucketOwnerEnforced`)
- Deploy role permission expansion for S3 bucket management (per CLAUDE.md decision)
- Outputs wired through root `outputs.tf`; `.env.example` updated for `VITE_S3_USER_SPACE_BUCKET`

### Out of Scope

- Shared-space bucket (Bucket 2) — access model still under redesign, future spec
- The portal IAM role and any user access to this bucket (SPEC-011/013)
- Bucket policy statements restricting access to the portal role (added in SPEC-013 when the role exists)
- Versioning and lifecycle rules (decide later; default off)
- Any application code

---

## Functional Requirements

### FR-001: `data` Module Scaffold

#### Description:

A new module at `infra/modules/data/` holds data-layer storage resources, composed from root `main.tf`.

#### Acceptance Criteria:

- [ ] `infra/modules/data/` exists with `s3.tf`, `variables.tf`, `outputs.tf`
- [ ] Root `main.tf` declares `module "data"` passing `project_name` and `app_url`
- [ ] `tofu validate` passes; no resources land in root-level `.tf` files

### FR-002: User-Space Bucket

#### Description:

The bucket that holds every user's prefix (`{username}/...`) and their future `connections.json` config.

#### Acceptance Criteria:

- [ ] Bucket named `${var.project_name}-prod-user-space` (overridable via `user_space_bucket_name` variable; default produces `dat-prod-user-space` with the current `project_name`)
- [ ] All four public access block settings enabled
- [ ] Server-side encryption with SSE-S3 (AES256) by default
- [ ] Object ownership set to `BucketOwnerEnforced` (ACLs disabled)
- [ ] Versioning explicitly disabled with a comment noting it's a deliberate MVP decision
- [ ] No bucket policy yet — a comment notes SPEC-013 adds the access policy once the portal role exists

### FR-003: CORS Configuration

#### Description:

Browser SDK calls fail without CORS. Configuration matches `docs/architecture.md`.

#### Acceptance Criteria:

- [ ] Allowed methods: GET, PUT, POST, DELETE, HEAD
- [ ] Allowed origins: `http://localhost:5173` plus `var.app_url` when non-empty
- [ ] Allowed headers: `*`; exposed headers: `ETag`, `x-amz-server-side-encryption`, `x-amz-request-id`, `x-amz-id-2`; `MaxAgeSeconds: 3000`
- [ ] `aws s3api get-bucket-cors` after apply returns the expected document

### FR-004: Deploy Role Permissions

#### Description:

Per the CLAUDE.md decision, the GitHub Actions deploy role must be able to manage the new resources.

#### Acceptance Criteria:

- [ ] The policy template under `infra/modules/base/policies/` is extended with the S3 bucket-management actions needed to create/read/update/tag/delete the user-space bucket and its configuration (CORS, encryption, public access block, ownership controls)
- [ ] Permissions scoped to the user-space bucket ARN pattern, not `s3:*` on `*`
- [ ] A `deploy-infra.yml` PR run plans this spec successfully using the deploy role

### FR-005: Outputs and Env Var Mapping

#### Description:

The bucket name reaches the app as an env var.

#### Acceptance Criteria:

- [ ] Module outputs `user_space_bucket_name` and `user_space_bucket_arn`
- [ ] Root `outputs.tf` exports `s3_user_space_bucket_name`
- [ ] `apps/portal/.env.example` `VITE_S3_USER_SPACE_BUCKET` comment updated to cite `tofu output s3_user_space_bucket_name` (SPEC-010)
- [ ] `.github/workflows/README.md` notes the new GitHub Actions variable needed by `deploy-app.yml` builds (consumed starting SPEC-013)

---

## Variables

| Variable | Location | Type | Required | Description |
|---|---|---|---|---|
| `user_space_bucket_name` | root + module (new) | string | no | Default `"${project_name}-prod-user-space"` |
| `app_url` | root (exists) | string | no | CORS origin for the deployed app |

---

## File & Folder Structure

```
infra/
├── main.tf                     ← + module "data" block
├── outputs.tf                  ← + s3_user_space_bucket_name
├── variables.tf                ← + user_space_bucket_name
└── modules/
    ├── base/policies/          ← extended deploy role policy
    └── data/                   ← NEW
        ├── s3.tf
        ├── variables.tf
        └── outputs.tf
```

---

## Implementation Phases

### Phase 1: Deploy role permissions + module + bucket

- Extend deploy role policy (FR-004)
- Scaffold `data` module with bucket, encryption, ownership, public access block (FR-001, FR-002)
- Add CORS (FR-003), outputs and env var docs (FR-005)

#### Checkpoint

`tofu validate` passes; `deploy-infra.yml` PR plan succeeds showing the bucket + CORS + deploy role policy change and nothing else. After merge/apply: bucket visible in console with public access blocked, `get-bucket-cors` returns the expected config, `tofu output s3_user_space_bucket_name` returns `dat-prod-user-space`.

## Open Questions

- [x] **Resolved (2026-06-10):** accept the literal `prod` in the default bucket name; introduce `var.environment` only when a staging environment is specced.
- [x] **Resolved (2026-06-10):** global name availability is checked at apply time (Phase 1 checkpoint); override via `user_space_bucket_name` if taken.
