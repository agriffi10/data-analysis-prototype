# ── Cognito User Pool ─────────────────────────────────────────────────────────
# Standalone User Pool for native username/password users (no external IdP).
# Sign-in is by username; email is a required, verified standard attribute.
#
# Username constraint: the username becomes the user's S3 prefix and the value of
# the `username` IAM principal tag stamped by the Identity Pool (SPEC-011). An IAM
# RoleSessionName / tag value allows at most 64 chars from the set
# `a-z A-Z 0-9 = , . @ - _` (see docs/architecture.md). Signup additionally enforces
# `^[a-zA-Z0-9._@-]{3,64}$` via the SPEC-012 pre-signup Lambda. Case-insensitivity
# (below) is immutable after pool creation, so `Alice` and `alice` must never become
# two distinct users / S3 prefixes.

resource "aws_cognito_user_pool" "portal" {
  name = "${var.project_name}-${var.environment}-user-pool"

  # Usernames are case-insensitive — immutable after pool creation.
  username_configuration {
    case_sensitive = false
  }

  # Signup requires an email verification code.
  auto_verified_attributes = ["email"]

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

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
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

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}

# ── Hosted UI Domain ──────────────────────────────────────────────────────────
# Cognito-managed domain hosting the login/signup pages. Full URL is
# <prefix>.auth.<region>.amazoncognito.com (exported from outputs.tf).

resource "aws_cognito_user_pool_domain" "portal" {
  domain       = local.domain_prefix
  user_pool_id = aws_cognito_user_pool.portal.id
}
