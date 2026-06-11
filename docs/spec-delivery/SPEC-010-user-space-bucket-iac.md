# Completed Spec - User-Space Bucket IaC — `data` Module

## What was completed from this spec?

Bucket 1 (user-space) is provisioned and live in a new bounded-context module
`infra/modules/data/`. This is the storage foundation for the entire
SPEC-010→014 data-access arc. Applied to the live account and verified on
2026-06-11.

- **`infra/modules/data/`** (`s3.tf`, `variables.tf`, `outputs.tf`):
  - Private bucket `dat-prod-user-space` (overridable via `user_space_bucket_name`), all four public-access-block settings on.
  - SSE-S3 (AES256) default encryption; `BucketOwnerEnforced` ownership (ACLs off).
  - Versioning explicitly **Disabled** (deliberate MVP decision — overwrites/deletes are irreversible, guarded in the UI).
  - CORS for browser SDK calls: `GET/PUT/POST/DELETE/HEAD`, origins = CloudFront domain + `http://localhost:5173`, exposes `ETag`/`x-amz-server-side-encryption`/`x-amz-request-id`/`x-amz-id-2`, `MaxAgeSeconds` 3000.
  - **No bucket policy** — SPEC-013 adds it once the portal role exists.
- **Cycle-free wiring** (`infra/main.tf`): the bucket name is computed once as a root `local` and shared two ways — `module.data` creates the bucket, and `module.base`'s deploy policy is scoped to the bucket ARN passed as a *constructed string* (so `base` has no dependency on `data`). `module.data` `depends_on = [module.base]`, mirroring `auth`.
- **IAM propagation guard**: a `time_sleep` (`hashicorp/time` provider, added to `providers.tf`) sits between the deploy-policy update and bucket creation, absorbing IAM eventual-consistency lag so the deploy role's freshly-added grant is active before it creates the bucket. Fires only on initial creation.
- **Deploy role** (`infra/modules/base/policies/github-actions-deploy.json.tftpl`): granted `s3:*` **scoped to the user-space bucket ARN** (mirrors the static-assets bucket). A curated action list was tried first but failed — see below.
- **Outputs / docs**: root output `s3_user_space_bucket_name`; `.env.example` `VITE_S3_USER_SPACE_BUCKET` cites `tofu output s3_user_space_bucket_name`; `.github/workflows/README.md` notes the new Actions variable (consumed starting SPEC-013).

### Verification

- `tofu validate` + `tofu fmt -check` clean; `tofu graph` confirmed no `data`→`base` cycle and the ordering (`base` policy → `module.data` → `time_sleep` → bucket).
- **Live checkpoint passed (2026-06-11):** `dat-prod-user-space` exists with all four public-access-block settings on, AES256 encryption, the expected CORS, and `tofu output s3_user_space_bucket_name` → `dat-prod-user-space`.

### First-apply incident + recovery (resolved)

The first apply failed: the deploy role's initially **enumerated** S3 action list
lacked `s3:GetBucketPolicy`, which the AWS provider's `aws_s3_bucket` read calls
(along with many other `GetBucket*` APIs) to populate computed attributes — even
for features we never set. The read 403'd *after* the bucket was physically
created, and because the bucket was then in state, every subsequent apply
deadlocked at plan/refresh before it could apply a fix.

- **Code fix:** deploy-role S3 statement changed to `s3:*` scoped to the bucket ARN.
- **One-time manual recovery (executed 2026-06-11):** a temporary `s3:*`-on-bucket inline policy was attached to `dat-deploy-role` to unblock refresh, the apply was re-run green, and the temp policy was removed. The rendered `deploy-policy` now permanently carries the `s3:*` statement.
- A clean (greenfield) apply needs none of this. Full runbook is in the spec's **Deployment Notes** section.

## What has changed?

- **`infra/providers.tf`** — added the `hashicorp/time` provider (`~> 0.12`) for the propagation guard.
- **`infra/main.tf`** — new root `local` for the bucket name; `module "data"` added; `module "base"` now receives `user_space_bucket_arn`.
- **`infra/variables.tf` / `infra/outputs.tf`** — added `user_space_bucket_name` (override) and the `s3_user_space_bucket_name` output.
- **`infra/modules/base/`** — `variables.tf` + `iam.tf` + the deploy-policy template gained the user-space bucket statement. This is the established pattern: any infra spec expands the deploy role for the resources it introduces.
- **`apps/portal/.env.example`** + **`.github/workflows/README.md`** — documentation of `VITE_S3_USER_SPACE_BUCKET` sourcing (build consumption begins in SPEC-013).

### Follow-ups / notes

- No app code changed; the file browser still uses the SPEC-002 test bucket until SPEC-013 switches it over.
- No bucket policy yet — SPEC-013 adds the policy restricting the bucket to the portal role (and break-glass account root).
- The lesson learned (provider refresh needs broad `GetBucket*`; grant `s3:*` scoped to the bucket; guard IAM propagation with `depends_on` + `time_sleep`) carries directly into SPEC-011's portal-role/identity-pool work.
