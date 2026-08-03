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
    provider_name           = "cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.portal.id}"
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
# not instantly (architecture.md, Bucket 2 membership-slot propagation note).
# `identity_provider_name` is built from `var.aws_region`, NOT `data.aws_region.current.name`,
# and that is load-bearing rather than stylistic.
#
# This module carries a module-level `depends_on = [module.base]` (main.tf). A module-level
# depends_on defers EVERY data source inside the module to apply time whenever the dependency
# has a pending change — and `module.base` changes on most PRs, since it holds the deploy-role
# policies. So `data.aws_region.current` came back "(known after apply)", which made
# `identity_provider_name` unknown at plan time, and it is a ForceNew attribute:
#
#   ~ identity_provider_name = "cognito-idp.us-east-1.amazonaws.com/us-east-1_zOlWYrE9K"
#         # forces replacement -> (known after apply) # forces replacement
#
# Every apply therefore destroyed and recreated the principal-tag mapping that the whole ABAC
# isolation model depends on (SPEC-011), on PRs that touched no auth code at all. It failed
# CLOSED, not open — the portal policy interpolates the tag into a Resource ARN
# (`${bucket_arn}/${aws:PrincipalTag/username}/*`), so an unstamped tag leaves the ARN
# unresolved and matches nothing — but a brief window where a fresh sign-in gets credentials
# that can read nothing is still a real outage, and it was recurring on every infra merge.
#
# `var.aws_region` is the same value by construction (providers.tf does `region =
# var.aws_region`) and is known at plan time, so the attribute stays static and the resource
# stops churning. Do NOT reintroduce the data source here.
#
# `ignore_changes` would have been the WRONG fix — compare the LF-grants case in
# docs/decisions.md, where `aws_lakeformation_permissions` genuinely reads back different
# values than were written and the drift is unavoidable. Here nothing drifts: the value is
# correct and constant, it was merely unknowable at plan time. Suppressing the diff would hide
# a real change to the provider name if the pool were ever recreated.
resource "aws_cognito_identity_pool_provider_principal_tag" "username" {
  identity_pool_id       = aws_cognito_identity_pool.portal.id
  identity_provider_name = "cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.portal.id}"
  use_defaults           = false

  principal_tags = merge(
    { username = "cognito:username" },
    { for k in range(1, var.max_shared_memberships + 1) : "shared_space_${k}" => "custom:shared_space_${k}" }
  )
}
