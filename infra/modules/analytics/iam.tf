# ── Lake Formation registration role ───────────────────────
# A CUSTOM role, deliberately NOT the LF service-linked one, so the trust and the S3 scope stay
# explicit and auditable. Scoped to the user-space bucket only. README.md.
resource "aws_iam_role" "lf_registration" {
  name               = "${var.project_name}-analytics-lf-registration-role"
  assume_role_policy = templatefile("${path.module}/policies/lf-registration-trust.json.tftpl", {})

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_iam_role_policy" "lf_registration" {
  name = "s3-location-access"
  role = aws_iam_role.lf_registration.id

  policy = templatefile("${path.module}/policies/lf-registration-permissions.json.tftpl", {
    bucket_arn = var.user_space_bucket_arn
  })
}

# ── Portal role — analytics permissions ────────────────────
# The portal role's SECOND inline policy. Glue is scoped to database/<username> and
# table/<username>/* via the `username` principal tag — THIS is the per-user isolation gate.
#
# ListQueryExecutions is OMITTED deliberately: it would leak other users' queries.
# s3:GetBucketLocation is required or Athena reports "Unable to verify/create output bucket";
# it leaks only the region. README.md.
resource "aws_iam_role_policy" "portal_analytics" {
  name = "analytics-access"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-analytics.json.tftpl", {
    aws_region            = var.aws_region
    account_id            = var.account_id
    workgroup_arn         = aws_athena_workgroup.portal.arn
    user_space_bucket_arn = var.user_space_bucket_arn
    principal_tag_key     = var.principal_tag_key
  })
}
