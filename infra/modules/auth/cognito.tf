# ── Cognito User Pool ─────────────────────────────────────────────────────────
# Standalone User Pool for native username/password users (no external IdP).
# Sign-in is by username; email is a required, verified standard attribute.
#
# Username constraint: the username becomes the user's S3 prefix, the value of the
# `username` IAM principal tag stamped by the Identity Pool, AND the
# user's Glue database name. An IAM RoleSessionName / tag value allows at
# most 64 chars from the set `a-z A-Z 0-9 = , . @ - _` (see docs/architecture.md).
# Signup additionally enforces `^[a-z][a-z0-9_]{2,62}$` via the pre-signup
# Lambda (a catalog-safe identifier, so the Glue DB name is
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
  # pre_sign_up — enforce the username rule server-side
  # post_confirmation — provision the user's Glue database + LF grant
  lambda_config {
    pre_sign_up       = aws_lambda_function.pre_signup.arn
    post_confirmation = aws_lambda_function.post_confirmation.arn
  }

  # Email verification uses a 6-digit code (not a link), so the user can enter it
  # on the Hosted UI. Customise the email so recipients recognise it. `{####}` is
  # the Cognito placeholder for the generated code.
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

  # Shared-space membership slots: custom:shared_space_1..N (mutable
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

  # Tightened for bot/credential-stuffing resistance. All flags
  # were already on; temporary_password_validity_days is added to complete the block.
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Self-signup enabled (open registration + email verification).
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
  # SES integration is deferred until real user volume exists.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Protects the user directory: a bad apply cannot destroy the pool.
  deletion_protection = "ACTIVE"
}

# `data "aws_region" "current"` used to live here and was REMOVED deliberately — see the
# comment on `aws_cognito_identity_pool_provider_principal_tag.username` in identity-pool.tf.
# Short version: this module carries a module-level `depends_on = [module.base]`, which defers
# EVERY data source in it to apply time whenever base has a pending change, so the region came
# back "(known after apply)" and forced a replace on the principal-tag mapping. `var.aws_region`
# is the same value (providers.tf configures the provider from it) and is known at plan time.

locals {
  # Callback/logout URLs always include local dev; each deployed origin is added only
  # when provided. BOTH deployed origins are listed, and that is the point: the container
  # is where ported features get proved and CloudFront is the rollback, so an app client
  # naming one of them makes the other an origin that cannot complete a sign-in. Removing
  # either is the cutover spec's work — doing it here deletes the rollback.
  #
  # distinct(), because the cutover re-points app_url AT the container origin before it
  # removes the entry: between those two steps the same URL appears twice, which Cognito
  # rejects outright rather than deduplicating.
  callback_urls = distinct(compact(["http://localhost:5173", var.app_url, var.spa_origin]))

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
  # so sign-in attempts can't enumerate registered accounts.
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
