# ── Cognito Identity Pool (SPEC-011) ─────────────────────────────────────────
# Exchanges the User Pool token for scoped AWS credentials (enhanced flow),
# authenticated identities only. Amplify v6 performs this exchange natively, so
# `fetchAuthSession()` returns credentials with no STS SDK in the app.
#
# Per-user isolation comes from "attributes for access control": the principal
# tag mapping below stamps the username claim onto a `username` principal tag
# SERVER-SIDE (unspoofable). The shared portal role and its prefix-scoped S3
# policy live in the data module (role trust here's audience; policy in SPEC-013).

# IAM propagation guard: this spec adds cognito-identity permissions to the deploy
# role (modules/base) in the same apply that then calls CreateIdentityPool. The
# module-level depends_on (auth -> base) orders the calls, but IAM is eventually
# consistent; this fresh time_sleep (created this apply, so it actually sleeps)
# absorbs the propagation window — same rationale as the SPEC-010 bucket guard.
resource "time_sleep" "wait_for_identity_perms" {
  create_duration = "30s"
}

resource "aws_cognito_identity_pool" "portal" {
  identity_pool_name               = "${var.project_name}-${var.environment}-identity-pool"
  allow_unauthenticated_identities = false
  allow_classic_flow               = false

  cognito_identity_providers {
    client_id               = aws_cognito_user_pool_client.spa.id
    provider_name           = "cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.portal.id}"
    server_side_token_check = true
  }

  depends_on = [time_sleep.wait_for_identity_perms]
}

# Attributes for access control — map the `username` principal tag to the user's
# username claim, asserted by AWS at credential issuance (never by the client).
# SPEC-013's role policy scopes S3 access with ${aws:PrincipalTag/username}.
#
# Claim key resolved (SPEC-011 FR-002, 2026-06-12): the tag VALUE must be the
# `cognito:username` claim. A first attempt mapping to `username` produced a
# CloudTrail AssumeRoleWithWebIdentity event with NO principalTags at all (the
# `username` claim doesn't exist in a Cognito User Pool ID token — it's
# `cognito:username`), so the tag was never stamped. The map key (`username`) is
# the tag NAME the role policy references; the value is the token claim it reads.
# SPEC-056 adds ten shared-space membership tags alongside `username`. There is only
# ONE principal-tag map per (pool, provider), so the slots are merged into this same
# resource: tag `shared_space_k` reads the `custom:shared_space_k` claim (cognito.tf).
# A slot the user isn't in carries no claim → the tag isn't stamped → the portal
# role's templated statement for that slot matches nothing (implicit deny). Grant/
# revoke takes effect on the NEXT token refresh (forced by SPEC-052's Refresh control),
# not instantly (shared-spaces-architecture.md §3 propagation note).
resource "aws_cognito_identity_pool_provider_principal_tag" "username" {
  identity_pool_id       = aws_cognito_identity_pool.portal.id
  identity_provider_name = "cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.portal.id}"
  use_defaults           = false

  principal_tags = merge(
    { username = "cognito:username" },
    { for k in range(1, var.max_shared_memberships + 1) : "shared_space_${k}" => "custom:shared_space_${k}" }
  )
}
