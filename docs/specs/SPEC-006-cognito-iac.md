# Spec: Cognito User Pool IaC — `auth` Module

**ID:** SPEC-006
**Status:** Draft
**Last Updated:** 2026-06-10
**Depends On:** SPEC-003 (IaC project), SPEC-005 (deploy-infra workflow applies changes)

## Overview

Provision the standalone AWS Cognito User Pool that will authenticate portal users, managed by OpenTofu as a new bounded-context module `infra/modules/auth/`. This is the infrastructure half of authentication: it creates the User Pool, the SPA app client, and the Hosted UI domain, and exports the identifiers the frontend needs as `VITE_*` env vars. No application code changes occur in this spec. SPEC-007 (login flow), SPEC-008 (gated layout), and SPEC-009 (signup) all depend on the resources created here.

## Scope

### In Scope

- New `infra/modules/auth/` module following the bounded-context module convention
- Cognito User Pool: native users, username sign-in, email required and verified, self-signup enabled
- User Pool Client configured for a SPA (no client secret, authorization code flow)
- Cognito Hosted UI domain (Cognito-prefixed subdomain — no custom domain)
- Callback/sign-out URLs covering local dev and the deployed CloudFront URL
- Module outputs wired through root `outputs.tf`
- `.env.example` updates mapping outputs to `VITE_*` variables
- Expanding the GitHub Actions deploy role's IAM permissions (`infra/modules/base/policies/`) to manage Cognito resources, so `deploy-infra.yml` can apply this spec

### Out of Scope

- The shared IAM portal role (`S3PortalRole`) and its session-tag trust policy — future spec, alongside the data buckets
- User-space / shared-space S3 buckets (Bucket 1 / Bucket 2) — future spec
- Any application code (Amplify config, login UI) — SPEC-007+
- Custom domain for the Hosted UI; ACM certificates
- Hosted UI custom branding/CSS (plain Hosted UI is acceptable for MVP)
- MFA, advanced security features, Lambda triggers (e.g. pre-signup domain restriction)
- Cognito groups, admin user management

---

## Functional Requirements

### FR-001: `auth` Module Scaffold

#### Description:

A new module at `infra/modules/auth/` holds all Cognito resources, composed from root `main.tf`, consistent with the existing `app` and `base` modules.

#### Acceptance Criteria:

- [ ] `infra/modules/auth/` exists with `cognito.tf`, `variables.tf`, `outputs.tf`
- [ ] Root `main.tf` declares `module "auth"` passing `project_name` and `app_url`
- [ ] `tofu validate` passes
- [ ] No resources are added to root-level `.tf` files — all Cognito resources live in the module

### FR-002: Cognito User Pool

#### Description:

A standalone User Pool for native username/password users. Email is a required, verified attribute. Self-signup is enabled (open registration with email verification — SPEC-009 depends on this).

#### Acceptance Criteria:

- [ ] User Pool is created with name derived from `var.project_name` (e.g. `${var.project_name}-user-pool`)
- [ ] Sign-in is by username; email is a required standard attribute
- [ ] `username_configuration.case_sensitive = false` — usernames are case-insensitive (immutable after pool creation; `Alice` and `alice` must not become distinct users/S3 prefixes)
- [ ] `auto_verified_attributes = ["email"]` — signup requires email code verification
- [ ] `admin_create_user_config.allow_admin_create_user_only = false` (self-signup enabled)
- [ ] Password policy: minimum length 12, require lowercase, uppercase, numbers, symbols
- [ ] Account recovery is via verified email only
- [ ] Username constraints documented in a comment: the username becomes the S3 prefix and IAM session tag — `RoleSessionName` allows max 64 chars from `a-z A-Z 0-9 = , . @ - _` (see `docs/architecture.md`)
- [ ] Deletion protection is enabled (`deletion_protection = "ACTIVE"`) so a bad apply cannot destroy the user directory

### FR-003: User Pool Client (SPA)

#### Description:

An app client the SPA uses via the Hosted UI OAuth authorization-code flow. SPAs cannot keep secrets, so no client secret is generated.

#### Acceptance Criteria:

- [ ] Client is created with `generate_secret = false`
- [ ] OAuth flows: `code` only (no implicit flow)
- [ ] OAuth scopes: `openid`, `email`, `profile`
- [ ] Callback URLs and logout URLs include both `http://localhost:5173` (local dev) and `var.app_url` (deployed CloudFront URL); when `var.app_url` is empty, only localhost is configured
- [ ] `supported_identity_providers = ["COGNITO"]` (native users only)
- [ ] Token validity left at Cognito defaults (1h access/id, 30d refresh) unless overridden by variable
- [ ] Auth session flows allow `ALLOW_USER_SRP_AUTH` and `ALLOW_REFRESH_TOKEN_AUTH`

### FR-004: Hosted UI Domain

#### Description:

A Cognito-managed domain hosts the login/signup pages the app redirects to.

#### Acceptance Criteria:

- [ ] A `aws_cognito_user_pool_domain` is created with a prefix derived from `var.project_name` (must be globally unique — expose a `cognito_domain_prefix` variable with a sensible default)
- [ ] The full domain (`<prefix>.auth.<region>.amazoncognito.com`) is exported as an output
- [ ] Visiting `https://<domain>/login?client_id=<clientId>&response_type=code&redirect_uri=<app_url>` renders the Hosted UI login page after apply

### FR-005: Deploy Role Permissions for Cognito

#### Description:

The GitHub Actions deploy role must be able to create and manage the Cognito resources this spec introduces, since `deploy-infra.yml` is the apply path. Per the CLAUDE.md decision, deploy role permission expansion is in-scope for any infra-provisioning spec.

#### Acceptance Criteria:

- [ ] The deploy role policy template under `infra/modules/base/policies/` is extended with the `cognito-idp` actions required to create, read, update, tag, and delete the User Pool, User Pool Client, and User Pool Domain
- [ ] Permissions are scoped as tightly as practical (resource ARNs where Cognito supports them; avoid blanket `cognito-idp:*` unless documented why)
- [ ] The deploy role change is applied **before or together with** the auth module so the workflow doesn't deadlock (note: applying the role change itself requires the role's own update path — document the ordering in the PR)
- [ ] A `deploy-infra.yml` run on a PR successfully plans the auth module using the deploy role (proves permissions suffice for plan; apply proves the rest on merge)

### FR-006: Outputs and Env Var Mapping

#### Description:

All values the frontend needs are exported from the module and surfaced through root `outputs.tf`.

#### Acceptance Criteria:

- [ ] Module outputs: `user_pool_id`, `user_pool_client_id`, `user_pool_domain`
- [ ] Root `outputs.tf` exports `cognito_user_pool_id`, `cognito_user_pool_client_id`, `cognito_domain`
- [ ] `apps/portal/.env.example` Cognito section is updated: comments change from "provisioned separately — not managed by infra/" to noting the values come from `tofu output` (SPEC-006)

---

## Variables

| Variable | Location | Type | Required | Description |
|---|---|---|---|---|
| `app_url` | root (exists) | string | no | Deployed app URL for callback/sign-out URLs. Already declared in SPEC-005 with default `""` — now consumed |
| `project_name` | root (exists) | string | no | Resource name prefix |
| `cognito_domain_prefix` | root + module (new) | string | no | Hosted UI domain prefix; default derived from `project_name` |

---

## Outputs

| Output | Maps to env var |
|---|---|
| `cognito_user_pool_id` | `VITE_COGNITO_USER_POOL_ID` |
| `cognito_user_pool_client_id` | `VITE_COGNITO_USER_POOL_CLIENT_ID` |
| `cognito_domain` | `VITE_COGNITO_DOMAIN` |

---

## File & Folder Structure

```
infra/
├── main.tf                     ← + module "auth" block
├── outputs.tf                  ← + cognito_* outputs
├── variables.tf                ← + cognito_domain_prefix
└── modules/
    └── auth/                   ← NEW
        ├── cognito.tf          ← user pool, client, domain
        ├── variables.tf
        └── outputs.tf
```

---

## Implementation Phases

### Phase 1: Deploy role permissions, module scaffold, User Pool

- Extend the deploy role policy in `infra/modules/base/policies/` with Cognito permissions (FR-005)
- Create `infra/modules/auth/` with variables and the User Pool resource (FR-001, FR-002)
- Wire `module "auth"` into root `main.tf`

#### Checkpoint

`tofu validate` passes and `tofu plan` shows exactly one User Pool to create with the configured password policy, self-signup enabled, and email auto-verification. Review plan output for `deletion_protection = "ACTIVE"`.

### Phase 2: Client, domain, outputs

- Add the User Pool Client and Hosted UI domain (FR-003, FR-004)
- Add module + root outputs; update `.env.example` (FR-006)

#### Checkpoint

`tofu plan` is clean. After apply (via the SPEC-005 `deploy-infra.yml` workflow or locally), `tofu output` shows all three Cognito values and the Hosted UI login page loads in a browser at the domain from FR-004.

## Open Questions

- [x] **Resolved (2026-06-10):** Hosted UI domain prefix defaults to `${project_name}-portal`; availability is checked at apply time (Phase 2 checkpoint) and overridden via `cognito_domain_prefix` if taken.
- [x] **Resolved (2026-06-10):** default Cognito email sender for MVP (50/day is ample for acceptance testing); SES integration deferred until real user volume exists.
