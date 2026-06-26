# ── Cognito User Pool ─────────────────────────────────────────────────────────
# Standalone User Pool for native username/password users (no external IdP).
# Sign-in is by username; email is a required, verified standard attribute.
#
# Username constraint: the username becomes the user's S3 prefix, the value of the
# `username` IAM principal tag stamped by the Identity Pool (SPEC-011), AND the
# user's Glue database name (SPEC-033). An IAM RoleSessionName / tag value allows at
# most 64 chars from the set `a-z A-Z 0-9 = , . @ - _` (see docs/architecture.md).
# Signup additionally enforces `^[a-z][a-z0-9_]{2,62}$` via the SPEC-012 pre-signup
# Lambda (tightened to a catalog-safe identifier by SPEC-033 so the Glue DB name is
# legal). Case-insensitivity (below) is immutable after pool creation, so `Alice` and
# `alice` must never become two distinct users / S3 prefixes.

resource "aws_cognito_user_pool" "portal" {
  name = "${var.project_name}-${var.environment}-user-pool"

  # Usernames are case-insensitive — immutable after pool creation.
  username_configuration {
    case_sensitive = false
  }

  # Signup requires an email verification code.
  auto_verified_attributes = ["email"]

  # Trigger Lambdas (defined in lambda.tf; invoke permission granted there):
  #   pre_sign_up       — enforce the username rule server-side (SPEC-012)
  #   post_confirmation — provision the user's Glue database + LF grant (SPEC-033)
  lambda_config {
    pre_sign_up       = aws_lambda_function.pre_signup.arn
    post_confirmation = aws_lambda_function.post_confirmation.arn
  }

  # Email verification uses a 6-digit code (not a link), so the user can enter it
  # on the Hosted UI. Customise the email so recipients recognise it. `{####}` is
  # the Cognito placeholder for the generated code (SPEC-009 FR-002).
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your S3 Portal verification code"
    email_message        = "Your S3 Portal verification code is {####}"
  }

  # Email is a required standard attribute.
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  # SPEC-056 shared-space membership slots: custom:shared_space_1..N (mutable
  # strings, not required). Each holds the name of a shared space the user belongs
  # to, or is unset. The Identity Pool maps each to a principal tag shared_space_k
  # (identity-pool.tf) and the portal-role policy scopes S3/Glue to
  # ${aws:PrincipalTag/shared_space_k}; an unset slot stamps no tag → implicit deny.
  # Only the privileged orchestrator role writes these (AdminUpdateUserAttributes).
  # ADDING custom attributes to an existing pool is an in-place AddCustomAttributes
  # (NOT a pool replacement); they cannot later be modified/removed, so the slot
  # count is effectively permanent — raise max_shared_memberships, never lower it.
  dynamic "schema" {
    for_each = range(1, var.max_shared_memberships + 1)
    content {
      name                = "shared_space_${schema.value}"
      attribute_data_type = "String"
      required            = false
      mutable             = true

      string_attribute_constraints {
        min_length = 0
        max_length = 256
      }
    }
  }

  # Tightened for bot/credential-stuffing resistance (SPEC-030 FR-002). All flags
  # were already on; temporary_password_validity_days is added to complete the block.
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Self-signup enabled (open registration + email verification) — SPEC-009 depends on this.
  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  # Account recovery via verified email only.
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Default Cognito email sender (50/day) is sufficient for MVP acceptance testing;
  # SES integration is deferred until real user volume exists (SPEC-006 open question).
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Protects the user directory: a bad apply cannot destroy the pool.
  deletion_protection = "ACTIVE"
}

data "aws_region" "current" {}

locals {
  # Callback/logout URLs always include local dev; the deployed app URL is added
  # only when provided (it is empty until the first CloudFront deploy).
  callback_urls = var.app_url != "" ? ["http://localhost:5173", var.app_url] : ["http://localhost:5173"]

  # Hosted UI domain prefix must be globally unique across all AWS accounts.
  domain_prefix = var.cognito_domain_prefix != "" ? var.cognito_domain_prefix : "${var.project_name}-${var.environment}-portal"
}

# ── User Pool Client (SPA) ────────────────────────────────────────────────────
# Public client for the SPA via the Hosted UI authorization-code flow. SPAs cannot
# keep a secret, so none is generated. Token validity is left at Cognito defaults
# (1h access/id, 30d refresh).

resource "aws_cognito_user_pool_client" "spa" {
  name         = "${var.project_name}-${var.environment}-spa-client"
  user_pool_id = aws_cognito_user_pool.portal.id

  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = local.callback_urls
  logout_urls   = local.callback_urls

  supported_identity_providers = ["COGNITO"]

  # Return an identical generic error for "user not found" and "wrong password"
  # so sign-in attempts can't enumerate registered accounts (SPEC-030 FR-001).
  # This is a free Cognito feature and does NOT require Advanced Security Features.
  prevent_user_existence_errors = "ENABLED"

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}

# ── Hosted UI Domain (Managed Login v2) ───────────────────────────────────────
# Cognito-managed domain hosting the login/signup pages. Full URL is
# <prefix>.auth.<region>.amazoncognito.com (exported from outputs.tf).
#
# managed_login_version = 2 serves the modern **Managed Login** UI instead of the
# classic Hosted UI. The classic UI did not reliably complete the OAuth redirect
# after a *self-service signup* email-code confirmation — the user landed
# confirmed-but-not-signed-in with no redirect back to the app. Managed Login
# carries the signup → confirm → auto-sign-in → redirect leg through to the
# callback, so account creation finishes signed-in (Amplify exchanges the
# returning code; the SPA then routes to /files). Requires a managed-login
# branding for the client (below).
resource "aws_cognito_user_pool_domain" "portal" {
  domain                = local.domain_prefix
  user_pool_id          = aws_cognito_user_pool.portal.id
  managed_login_version = 2
}

# Managed Login also requires a branding style per app client, or the v2 pages
# fail to render. The native `aws_cognito_managed_login_branding` resource only
# exists in the AWS provider's 6.x line; this repo is pinned to `~> 5.0` (which
# DOES support `managed_login_version` above but NOT the branding resource).
# Rather than take a risky provider major-version bump for one resource, the
# Cognito-provided default branding is ensured imperatively in CI after apply
# (deploy-infra.yml) — the same "Terraform owns infra, CI owns imperative
# deploy steps" split used for Lambda code. Revisit (move to the native
# resource) if/when the provider is upgraded to 6.x.
