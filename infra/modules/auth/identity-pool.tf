# ── Cognito Identity Pool ─────────────────────────────────────────
# Exchanges the User Pool token for scoped AWS credentials, authenticated identities only.
# The role and its policy live in modules/data. README.md.

# IAM propagation guard: the deploy role's cognito-identity grant is written in the same
# apply that calls CreateIdentityPool.
resource "time_sleep" "wait_for_identity_perms" {
  create_duration = "30s"
}

resource "aws_cognito_identity_pool" "portal" {
  identity_pool_name               = "${var.project_name}-${var.environment}-identity-pool"
  allow_unauthenticated_identities = false
  allow_classic_flow               = false

  cognito_identity_providers {
    client_id               = aws_cognito_user_pool_client.spa.id
    provider_name           = "cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.portal.id}"
    server_side_token_check = true
  }

  depends_on = [time_sleep.wait_for_identity_perms]
}

# Attributes for access control. The tag is stamped SERVER-SIDE at credential issuance and is
# unspoofable — this resource IS the isolation model.
#
# THE TAG VALUE MUST BE `cognito:username`. Mapping to `username` produces an
# AssumeRoleWithWebIdentity event with NO principalTags at all, because that claim does not
# exist in a Cognito ID token. The key is the tag NAME; the value is the CLAIM.
#
# ONE principal-tag map exists per (pool, provider), which is why the membership slots are
# merged into this resource rather than declared separately.
#
# ⚠ `identity_provider_name` is built from `var.aws_region`, NEVER
# `data.aws_region.current.name`. It is a ForceNew attribute, and a module-level depends_on
# makes every data source unknown at plan time — which replaced this resource on every infra
# merge. DO NOT REINTRODUCE THE DATA SOURCE. ignore_changes is NOT the fix. README.md.
resource "aws_cognito_identity_pool_provider_principal_tag" "username" {
  identity_pool_id       = aws_cognito_identity_pool.portal.id
  identity_provider_name = "cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.portal.id}"
  use_defaults           = false

  principal_tags = merge(
    { username = "cognito:username" },
    { for k in range(1, var.max_shared_memberships + 1) : "shared_space_${k}" => "custom:shared_space_${k}" }
  )
}
