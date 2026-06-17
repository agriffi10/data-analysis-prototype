# Completed Spec — SPEC-032: Analytics Foundation IaC

## What was completed from this spec?

The infrastructure foundation for the in-app Athena query feature (analytics arc
SPEC-032→036). Pure OpenTofu — a new `infra/modules/analytics/` module plus a
deploy-role expansion. No app code, no per-user databases (SPEC-033), no LF-Tags
(isolation is the `username` IAM principal tag).

**New module `infra/modules/analytics/`:**
- `athena.tf` — shared workgroup `dat-prod-portal-wg`: `enforce_workgroup_configuration = false`
  (app supplies a per-user `OutputLocation`; IAM is the real boundary), engine v3
  pinned, CloudWatch metrics on, 10 GiB `bytes_scanned_cutoff_per_query` guardrail,
  default output → the admin bucket, SSE-S3. (FR-002)
- `s3.tf` — admin-only `dat-prod-athena-admin`: all public-access-block on, SSE-S3,
  `BucketOwnerEnforced`, versioning off, 30-day lifecycle expiry, **no portal-role
  access**, no CORS. (FR-003)
- `lakeformation.tf` — `aws_lakeformation_data_lake_settings` (admins +
  empty `create_*_default_permissions` to drop the `IAMAllowedPrincipals` Super
  grants so LF enforces), hybrid-mode `aws_lakeformation_resource` registration of
  the user-space bucket, and an `aws_lakeformation_permissions`
  `DATA_LOCATION_ACCESS` grant to the portal role. (FR-004, FR-005)
- `iam.tf` — the **custom** LF registration role (not the service-linked role) +
  its scoped S3 policy, and the portal role's second inline policy
  (`analytics-access`). (FR-005, FR-006)
- `policies/` — `lf-registration-trust.json.tftpl`, `lf-registration-permissions.json.tftpl`,
  `portal-role-analytics.json.tftpl`.
- `variables.tf`, `outputs.tf` (`athena_workgroup_name`, `athena_admin_bucket_name`).

**Portal-role analytics policy (FR-006)** — Glue scoped to
`database/${aws:PrincipalTag/username}` + `table/${aws:PrincipalTag/username}/*`
(the per-user isolation gate; `GetDatabases` omitted), Athena workgroup-scoped
(`ListQueryExecutions` omitted — it would leak other users' queries), LF
`GetDataAccess`, results `Get/PutObject` on `{username}/athenaresults/*` with an
explicit **`Deny` on `DeleteObject`** there. Source-data + CTAS/INSERT writes ride
on SPEC-013's existing `${aws:PrincipalTag/username}/*` grants — no new statement.

**Deploy-role expansion (FR-007)** in `modules/base/policies/github-actions-deploy.json.tftpl`:
Athena workgroup mgmt (scoped to `${project_name}-*`), Glue catalog/db mgmt, Lake
Formation admin/grant/register actions, `s3:*` on the admin bucket, and the LF
registration-role mgmt + `iam:PassRole`. (No LF-Tag actions; no service-linked-role
permission — we use a custom registration role.)

**Root wiring + docs (FR-001, FR-008):** `main.tf` locals (cycle-free names/ARNs)
+ `module "analytics"` (`depends_on = [module.base, module.data]`), root
`variables.tf` (`workgroup_name`, `athena_admin_bucket_name`, `principal_tag_key`,
`lambda_provisioner_role_arn`), `outputs.tf` (`athena_workgroup_name`,
`athena_admin_bucket_name`), `apps/portal/.env.example` + `.github/workflows/README.md`
(`VITE_ATHENA_WORKGROUP`).

## What has changed?

- **`modules/base`** — deploy-role policy template + `variables.tf` (`athena_admin_bucket_arn`)
  + `iam.tf` (`templatefile` arg) extended. Purely additive; no existing statement changed.
- **Root `main.tf` / `variables.tf` / `outputs.tf`** — new locals, module block, vars,
  outputs. No change to existing modules' wiring.
- No application code, no existing-spec behavior changed.

### Key decisions / deviations

- **Custom LF registration role, not the service-linked role** (per the user's
  instruction). `dat-analytics-lf-registration-role` trusts `lakeformation.amazonaws.com`
  and is scoped to read/write the user-space bucket; the `iam:CreateServiceLinkedRole`
  deploy permission was removed.
- **`lambda_provisioner_role_arn` made optional** (spec said Required) — resolves the
  spec's open ordering question. LF `admins = compact([deploy_role_arn, lambda_provisioner_role_arn])`,
  so 032 deploys standalone (deploy role as the only admin); SPEC-033 fills the var
  and a re-apply adds its Lambda role as an LF admin.
- **Isolation is the IAM `username` principal tag** on the Glue database/table ARNs —
  not LF-Tags (explicitly rejected). LF authorizes the shared role broadly (per-DB
  grant comes from SPEC-033's Lambda); IAM is the per-user gate.

### Verification

`tofu fmt` clean and `tofu validate` passes. Because `validate` does not render
`templatefile()`, all changed/new policy templates were additionally rendered via
`tofu console` and `jsondecode`d — confirming valid JSON and that the nested escape
`$${aws:PrincipalTag/${principal_tag_key}}` renders to `${aws:PrincipalTag/username}`.

**Deferred to deploy time (no local AWS):** the `deploy-infra.yml` PR `tofu plan`, then
apply, then the FR checkpoints — `tofu output athena_workgroup_name`; a manual
`SELECT 1` against the admin bucket; the default `IAMAllowedPrincipals` Super grant
gone; `aws lakeformation describe-resource` shows the hybrid registration; and the
**file-browser hybrid-mode regression check** (SPEC-013 direct-S3 access still works
against the now-registered bucket). The end-to-end per-user query proof is deferred to
SPEC-033 (needs a real per-user database + the per-DB LF grant its Lambda issues).
