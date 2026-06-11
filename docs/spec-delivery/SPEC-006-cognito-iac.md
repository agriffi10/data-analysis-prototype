# Completed Spec - Cognito User Pool IaC — `auth` Module

## What was completed from this spec?

A new bounded-context OpenTofu module `infra/modules/auth/` that provisions the standalone Cognito User Pool the portal authenticates against, plus the SPA app client and Hosted UI domain. No application code changed — this is the infrastructure half of authentication, consumed by SPEC-007+.

- `infra/modules/auth/cognito.tf`:
  - `aws_cognito_user_pool.portal` — name `${project_name}-${environment}-user-pool` (resolves to `dat-prod-user-pool`). Username sign-in; `email` is a required, verified standard attribute (`auto_verified_attributes = ["email"]`). `username_configuration.case_sensitive = false` (immutable; keeps `Alice`/`alice` from becoming distinct S3 prefixes). Self-signup enabled (`allow_admin_create_user_only = false`). Password policy: min length 12, lower + upper + numbers + symbols. Account recovery via verified email only. Default Cognito email sender (50/day — sufficient for MVP). `deletion_protection = "ACTIVE"`. The username constraint (S3 prefix + `username` principal tag; 64-char RoleSessionName limit; SPEC-012 regex) is documented in a header comment.
  - `aws_cognito_user_pool_client.spa` — name `${project_name}-${environment}-spa-client`. `generate_secret = false`, `allowed_oauth_flows = ["code"]`, scopes `openid`/`email`/`profile`, `supported_identity_providers = ["COGNITO"]`, `explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]`. Token validity left at Cognito defaults. Callback/logout URLs always include `http://localhost:5173`, and append `var.app_url` only when it is non-empty.
  - `aws_cognito_user_pool_domain.portal` — Cognito-prefixed Hosted UI domain (`${project_name}-${environment}-portal` → `dat-prod-portal` by default; overridable via `cognito_domain_prefix`).
- `infra/modules/auth/variables.tf` — `project_name`, `environment`, `app_url`, `cognito_domain_prefix`.
- `infra/modules/auth/outputs.tf` — `user_pool_id`, `user_pool_client_id`, `user_pool_domain` (the last constructed as `<prefix>.auth.<region>.amazoncognito.com` via `data.aws_region.current`).

### Verification

- `tofu validate` passes.
- `tofu plan` is clean: **3 to add** (pool, client, domain), **1 to change** (deploy-role policy), **0 to destroy**. Plan output confirms `deletion_protection = "ACTIVE"`, self-signup, email auto-verification, and the password policy.
- **Pending (verified on merge via `deploy-infra.yml`):** apply has not been run. Per FR-005, the PR plan proves the deploy role can read/plan Cognito, and the merge-to-`main` apply proves create permissions. After apply, `tofu output` surfaces the three `cognito_*` values and the Hosted UI login page loads at the domain. Consistent with SPEC-003, this spec is marked Completed though not yet applied to AWS.

## What has changed?

- **`infra/main.tf`** — added `module "auth"` (passing `project_name`, `environment`, `app_url`, `cognito_domain_prefix`); updated the module-composition header comment to list `auth`.
- **`infra/variables.tf`** — added two new root variables:
  - `environment` (string, default `"prod"`) — establishes the `{project_name}-{environment}` resource-naming convention for resources going forward. Existing `app`/`base` resources were intentionally **not** renamed (would force destroy/recreate); migrating them is deferred.
  - `cognito_domain_prefix` (string, default `""`) — Hosted UI domain prefix override; empty falls back to `{project_name}-{environment}-portal`.
- **`infra/outputs.tf`** — added `cognito_user_pool_id`, `cognito_user_pool_client_id`, `cognito_domain`, wired through `module.auth`.
- **`infra/modules/base/policies/github-actions-deploy.json.tftpl`** — extended the deploy-role policy with Cognito permissions (FR-005):
  - `CognitoManage` statement scoped to `arn:aws:cognito-idp:${aws_region}:*:userpool/*` — describe/update/delete on the pool, full CRUD on the app client and domain, plus tagging actions.
  - `CognitoCreatePool` statement granting `cognito-idp:CreateUserPool` on `*`. **Rationale:** `CreateUserPool` does not support resource-level permissions (no pool ARN exists at creation time), so it cannot be scoped tighter. This is the documented exception to avoiding blanket grants — every other `cognito-idp` action is scoped to the user-pool ARN. (IAM policy JSON cannot carry inline comments and rejects unknown statement keys, so this rationale lives here rather than in the template.)

  **Deploy ordering note (FR-005):** the deploy role updates its own policy via the `IAMSelfManage` statement, so applying the Cognito permission expansion and the auth module together in one `deploy-infra.yml` run on merge does not deadlock — the role already holds `iam:PutRolePolicy` on itself.
- **`apps/portal/.env.example`** — Cognito section comments updated from "provisioned separately — not managed by infra/" to note the values come from `tofu output` (mapping each output to its `VITE_*` variable).
