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
  # matches nothing — implicit deny. Only the orchestrator role writes these: no app client's
  # write_attributes names one, and an admin call under IAM is not limited by a client's list.
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
  # Hosted UI domain prefix must be globally unique across all AWS accounts.
  domain_prefix = var.cognito_domain_prefix != "" ? var.cognito_domain_prefix : "${var.project_name}-${var.environment}-portal"
}

# ── User Pool Client (the portal server) ──────────────────────────────────────
# Confidential: the Next.js server runs the authorization-code flow and holds the tokens, so it can
# keep a secret and the browser never sees one. It and the dev client below share every sign-in
# setting and differ only in their one callback and sign-out URL.
#
# BOTH ATTRIBUTE LISTS ON EVERY CLIENT, SET TOGETHER. The write list is email alone, so no user can
# write a custom:shared_space_k slot into their own account through a client. The read list must name
# EVERY slot: one it omits drops that claim from the ID token, and a missing membership claim presents
# as the documented propagation delay rather than as a fault. Setting the write list alone could send
# the read list back to a default one AWS document says excludes custom attributes. README.md.
locals {
  # The one read list every client references, built from the same range as the pool's slot schema.
  client_read_attributes = concat(
    ["email", "email_verified"],
    [for k in range(1, var.max_shared_memberships + 1) : "custom:shared_space_${k}"],
  )

  # One source for the server client's token lifetimes and the session's ceiling, so a session can
  # never outlive the refresh token that keeps it alive.
  server_token_validity = {
    id_minutes     = 60
    access_minutes = 60
    refresh_days   = 30
  }
}

resource "aws_cognito_user_pool_client" "server" {
  name         = "${var.project_name}-${var.environment}-server-client"
  user_pool_id = aws_cognito_user_pool.portal.id

  generate_secret = true

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = ["${var.spa_origin}/auth/callback"]
  logout_urls   = [var.spa_origin]

  supported_identity_providers = ["COGNITO"]

  prevent_user_existence_errors = "ENABLED"

  write_attributes = ["email"]
  read_attributes  = local.client_read_attributes

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Revocation is what the server's sign-out revokes the refresh token through, and what makes
  # Cognito emit jti. Rotation is OFF: with it on, a refresh whose process dies between Cognito's
  # answer and the store's write leaves a refresh token Cognito revokes after its grace period,
  # which signs the user out for no reason they can see. The refresh token never leaves the server.
  enable_token_revocation = true

  # The grace period is stated although rotation is off, because the provider plans an omitted one
  # as null and then reads AWS's 0 back: the create succeeds in AWS and the apply fails as an
  # inconsistent result, leaving everything that depends on the client unapplied.
  refresh_token_rotation {
    feature                    = "DISABLED"
    retry_grace_period_seconds = 0
  }

  id_token_validity      = local.server_token_validity.id_minutes
  access_token_validity  = local.server_token_validity.access_minutes
  refresh_token_validity = local.server_token_validity.refresh_days

  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
}

# The server client's secret, delivered to the container by ECS from here. OUTSIDE the web tier's
# switch with the client it belongs to. A SecureString under the AWS-managed key: ECS's execution
# role reads it with ssm:GetParameters alone. The secret is in Terraform state either way, because
# the client's own client_secret attribute already is.
resource "aws_ssm_parameter" "server_client_secret" {
  name  = var.client_secret_parameter_name
  type  = "SecureString"
  value = aws_cognito_user_pool_client.server.client_secret

  tags = { Name = "${var.project_name}-${var.environment}-oidc-client-secret" }
}

# ── User Pool Client (local development) ──────────────────────────────────────
# A second client, so a laptop signs in through the portal server's own routes under `next dev` with a
# secret of its own: a laptop can be cut off without touching production, and the server client's
# lists never name localhost. It MIRRORS the server client in every setting and differs only in its
# one callback and one sign-out URL.
resource "aws_cognito_user_pool_client" "dev" {
  name         = "${var.project_name}-${var.environment}-dev-client"
  user_pool_id = aws_cognito_user_pool.portal.id

  generate_secret = true

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = ["${var.dev_origin}/auth/callback"]
  logout_urls   = [var.dev_origin]

  supported_identity_providers = ["COGNITO"]

  prevent_user_existence_errors = "ENABLED"

  write_attributes = ["email"]
  read_attributes  = local.client_read_attributes

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  enable_token_revocation = true

  refresh_token_rotation {
    feature                    = "DISABLED"
    retry_grace_period_seconds = 0
  }

  id_token_validity      = local.server_token_validity.id_minutes
  access_token_validity  = local.server_token_validity.access_minutes
  refresh_token_validity = local.server_token_validity.refresh_days

  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }
}

# Everything a local server needs, as one JSON object `npm run dev:session-env` writes into
# `apps/portal/.env.local`. Root builds every value from the locals the task definition's
# environment comes from, so the two cannot drift; only the dev client's own id and secret are added
# here. A SecureString under the AWS-managed key, like the server's secret, and never an output.
resource "aws_ssm_parameter" "dev_session_environment" {
  name = var.dev_session_parameter_name
  type = "SecureString"
  value = jsonencode(merge(var.dev_session_environment, {
    OIDC_CLIENT_ID     = aws_cognito_user_pool_client.dev.id
    OIDC_CLIENT_SECRET = aws_cognito_user_pool_client.dev.client_secret
  }))

  tags = { Name = "${var.project_name}-${var.environment}-dev-session-env" }
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
