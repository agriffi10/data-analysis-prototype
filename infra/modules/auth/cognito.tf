# ── Cognito User Pool ─────────────────────────────────────────────────────────
# Standalone, native username/password, no external IdP.
#
# ONE STRING IS FOUR THINGS: the username is the S3 prefix, the `username` principal tag and
# the Glue database name. Case-insensitivity below is IMMUTABLE after pool creation, so
# `Alice` and `alice` must never become two users. README.md.

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
    pre_sign_up       = module.pre_signup.function_arn
    post_confirmation = module.post_confirmation.function_arn
  }

  # Email verification uses a 6-digit code (not a link), so the user can enter it
  # on the Hosted UI. Customise the email so recipients recognise it. `{####}` is
  # the Cognito placeholder for the generated code.
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your Data Quarry verification code"
    email_message        = "Your Data Quarry verification code is {####}"
  }

  # Email is a required standard attribute.
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  # Shared-space membership slots. An unset slot stamps no tag, so that slot's statement
  # matches nothing — implicit deny. Only the orchestrator role writes these.
  #
  # CUSTOM ATTRIBUTES CAN NEVER BE MODIFIED OR REMOVED once added, so the slot count is
  # effectively permanent: RAISE max_shared_memberships, NEVER LOWER IT.
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

  # Tightened for bot/credential-stuffing resistance.
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

  # Cognito's default sender is 50/day. SES is deferred until real user volume exists.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Protects the user directory: a bad apply cannot destroy the pool.
  deletion_protection = "ACTIVE"
}

# ⚠ `data "aws_region" "current"` was REMOVED from this module and MUST NOT COME BACK. A
# module-level depends_on defers every data source to apply time, and a deferred value on a
# ForceNew attribute plans a replacement — which is how the principal-tag mapping this module
# used to hold was replaced on every infra merge. README.md.

locals {
  # ONE deployed origin. It was two through the cutover, because naming one made the other
  # unable to complete a sign-in — that is what made CloudFront a rollback rather than a URL.
  # The distribution is gone, so a second entry would now admit an origin nothing serves.
  #
  # distinct() and compact() both stay: Cognito REJECTS a duplicate rather than deduplicating,
  # and an unset spa_origin must drop out rather than reach Cognito as an empty string.
  callback_urls = distinct(compact(["http://localhost:5173", var.spa_origin]))

  # Hosted UI domain prefix must be globally unique across all AWS accounts.
  domain_prefix = var.cognito_domain_prefix != "" ? var.cognito_domain_prefix : "${var.project_name}-${var.environment}-portal"
}

# ── User Pool Client (SPA) ────────────────────────────────────────────────────
# Public client, authorization-code flow. SPAs cannot keep a secret, so none is generated.

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

  # Identical generic error for "user not found" and "wrong password", so sign-in cannot
  # enumerate accounts. Free — it does NOT require Advanced Security Features.
  prevent_user_existence_errors = "ENABLED"

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}

# ── Hosted UI Domain (Managed Login v2) ───────────────────────────────────────
# Version 2, NOT the classic Hosted UI: the classic one did not reliably complete the OAuth
# redirect after a self-service signup confirmation, leaving the user confirmed-but-not-
# signed-in. README.md.
resource "aws_cognito_user_pool_domain" "portal" {
  domain                = local.domain_prefix
  user_pool_id          = aws_cognito_user_pool.portal.id
  managed_login_version = 2
}

# Managed Login ALSO requires a per-client branding style or the v2 pages fail to render.
# The native resource is provider 6.x only and this repo is pinned to ~> 5.0, so CI ensures
# the default branding after apply (deploy-infra.yml). README.md.
