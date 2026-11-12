# ── Portal role — shared-space membership policy ────────────
# The portal role's THIRD inline policy, attached BY NAME. FIXED SIZE — ten slots regardless of
# how many spaces exist — so it stays inside the role's inline-policy aggregate.
#
# Each slot is templated on ${aws:PrincipalTag/shared_space_k}; an unset slot stamps no tag, so
# the statement matches nothing. Verified with simulate-custom-policy.
#
# The archive-receipt Deny uses the WILDCARD SPACE SEGMENT rather than a per-slot loop, and
# that is NOT a shortcut: A DENY NEEDS NO TAG TO BE CORRECT, so one statement covers every slot
# including ones the user does not hold — where the per-slot ALLOWS must be tag-scoped or they
# would grant access to spaces the user is not in. README.md.
resource "aws_iam_role_policy" "portal_shared_space" {
  name = "shared-space-membership"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-shared-space.json.tftpl", {
    shared_space_bucket_arn = aws_s3_bucket.shared_space.arn
    aws_region              = var.aws_region
    account_id              = var.account_id
    max_shared_memberships  = var.max_shared_memberships
  })
}
