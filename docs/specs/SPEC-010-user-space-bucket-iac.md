---
type: Spec
id: SPEC-010
title: "User-Space Bucket IaC — `data` Module"
description: "Gives operators an OpenTofu data module that provisions the user-space S3 bucket, where each user's files live under their own username prefix, with its browser CORS configuration and deploy-role permissions."
spec_status: Completed
depends_on: [SPEC-003, SPEC-005]
---

**Dependency notes:** SPEC-003 (IaC project), SPEC-005 (deploy-infra workflow)
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

- [ ] The policy template under `infra/modules/base/policies/` grants the deploy role `s3:*` **scoped to the user-space bucket ARN** (`arn:aws:s3:::{bucket}` and `/*`), mirroring the static-assets bucket statement. A curated action list is intentionally avoided: the AWS provider's `aws_s3_bucket` read/refresh calls many `GetBucket*` sub-resource APIs (policy, ACL, logging, lifecycle, replication, …) on every plan/apply even when those features are unset, so an enumerated list breaks (e.g. `GetBucketPolicy` 403)
- [ ] Permissions scoped to the user-space bucket ARN pattern, **not** `s3:*` on `*`
- [ ] A `deploy-infra.yml` PR run plans this spec successfully using the deploy role
- [ ] Apply ordering is enforced so the deploy-role grant lands before the bucket is created: `module.data` declares `depends_on = [module.base]`, and the bucket waits on a `time_sleep` (`hashicorp/time` provider) to absorb the IAM eventual-consistency window — preventing a transient `AccessDenied` when the deploy role uses its freshly-added S3 permission in the same apply. The bucket name is computed once as a root `local` and the ARN is passed to `base` as a constructed string, so there is no `data`→`base` dependency cycle

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

> **Checkpoint result (verified 2026-06-11):** ✅ Passed against the live account.
> `dat-prod-user-space` exists with all four public-access-block settings on,
> AES256 encryption, and the expected CORS (`GET/PUT/POST/DELETE/HEAD`, CloudFront
> + localhost origins, `ETag`/SSE/request-id exposed). `tofu output
> s3_user_space_bucket_name` → `dat-prod-user-space`.

## Deployment Notes

### First-apply recovery: `GetBucketPolicy` 403 + refresh deadlock (2026-06-11)

The first `deploy-infra` apply on merge **failed**, and the situation needed a
one-time manual unblock. Captured here so the next environment doesn't repeat it.

**What happened.** The deploy-role policy initially used an *enumerated* S3 action
list. `module.base` (the policy) applied before `module.data`, so the deploy role
gained those actions and then created the bucket — but the AWS provider's
`aws_s3_bucket` read calls a broad family of `GetBucket*` APIs (`GetBucketPolicy`,
ACL, logging, lifecycle, replication, …) to populate computed attributes, even for
features we never set. The enumerated list lacked `GetBucketPolicy`, so the
post-create read 403'd and the apply errored **after the bucket physically
existed**. Because the bucket was now in state, every subsequent apply failed at
the **plan/refresh** step (reading the existing bucket with the still-old policy)
*before* it could apply the policy fix — a deadlock the pipeline can't self-heal.

**The fix in code.** The deploy-role statement was changed to `s3:*` scoped to the
bucket ARN (`arn:aws:s3:::dat-prod-user-space` + `/*`), mirroring the static-assets
bucket — see FR-004. A curated list is not used because the provider's refresh
touches more sub-resources than we configure.

**One-time manual recovery** (needed only because a partial apply had already run):

```bash
# 1. Out-of-band, grant the deploy role full access to just this bucket so the
#    next plan/refresh can read it (admin creds):
aws iam put-role-policy --role-name dat-deploy-role --policy-name temp-userspace-unblock \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:*","Resource":["arn:aws:s3:::dat-prod-user-space","arn:aws:s3:::dat-prod-user-space/*"]}]}'

# 2. Re-run the deploy-infra apply. It refreshes cleanly, then re-renders the
#    deploy policy to `s3:*` on the bucket and reconciles the bucket.

# 3. Remove the temp policy (the rendered deploy-policy now covers it):
aws iam delete-role-policy --role-name dat-deploy-role --policy-name temp-userspace-unblock
```

This was executed on 2026-06-11; the apply went green and the temp policy was
removed. A clean (greenfield) apply does **not** need any of this — the `s3:*`
scope is correct from the start, so the bucket's create-then-read succeeds on the
first try.

## Open Questions

- [x] **Resolved (2026-06-10):** accept the literal `prod` in the default bucket name; introduce `var.environment` only when a staging environment is specced.
- [x] **Resolved (2026-06-10):** global name availability is checked at apply time (Phase 1 checkpoint); override via `user_space_bucket_name` if taken.
