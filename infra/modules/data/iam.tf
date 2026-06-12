# ── Portal Role (shared, trust only) ─────────────────────────────────────────
# The single IAM role every authenticated user assumes via the Identity Pool
# (SPEC-011). Trust ONLY — no permission policy is attached here; SPEC-013 adds
# the prefix-scoped S3 policy. Per-user isolation is enforced by the `username`
# principal tag the Identity Pool stamps server-side (auth module), evaluated by
# SPEC-013's policy via ${aws:PrincipalTag/username}. One role for all users.

# IAM propagation guard: this spec grants the deploy role iam:CreateRole/PassRole
# on this role name (modules/base) in the same apply that creates the role. Fresh
# time_sleep (created this apply) absorbs the propagation window — see the bucket
# guard in s3.tf for the full rationale.
resource "time_sleep" "wait_for_portal_role_perms" {
  create_duration = "30s"
}

resource "aws_iam_role" "portal" {
  name = var.portal_role_name

  # Trust the Identity Pool (not the User Pool directly): authenticated identities
  # from this pool may AssumeRoleWithWebIdentity and TagSession (the latter is
  # required for the principal tag mapping to take effect).
  assume_role_policy = templatefile("${path.module}/policies/portal-role-trust.json.tftpl", {
    identity_pool_id = var.identity_pool_id
  })

  depends_on = [time_sleep.wait_for_portal_role_perms]
}

# Bind the portal role as the Identity Pool's authenticated role. The pool ID is
# passed in from the auth module, keeping the dependency one-directional
# (data -> auth) with no cycle.
resource "aws_cognito_identity_pool_roles_attachment" "portal" {
  identity_pool_id = var.identity_pool_id

  roles = {
    authenticated = aws_iam_role.portal.arn
  }
}

# ── Prefix-Scoped Permission Policy (SPEC-013 FR-001) ────────────────────────
# Turns on real S3 access: each session may read/write/delete only under its own
# {username}/ prefix, where {username} is the `username` principal tag the Identity
# Pool stamps server-side (SPEC-011) — never asserted by the client. A session
# without the tag matches nothing, so it gets an implicit deny (no access). The
# tag variable is escaped as $${aws:PrincipalTag/username} in the template so
# templatefile() emits it literally instead of interpolating it.
resource "aws_iam_role_policy" "portal_permissions" {
  name = "user-space-access"
  role = aws_iam_role.portal.id

  policy = templatefile("${path.module}/policies/portal-role-permissions.json.tftpl", {
    bucket_arn = aws_s3_bucket.user_space.arn
  })
}
