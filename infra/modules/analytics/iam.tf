# ── Lake Formation registration role ───────────────────────
# A CUSTOM role (deliberately NOT the LF service-linked role) that Lake Formation
# assumes to vend temporary S3 credentials for the registered user-space location.
# Using our own role keeps the trust and the S3 scope explicit and auditable; it is
# scoped to read/write the user-space bucket only. The deploy role can create and
# pass this exact role name (modules/base LakeFormationRegistrationRole, FR-007).
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
# A SECOND inline policy on the shared portal role (the first, "user-space-access",
# is attached by module.data / SPEC-013). Glue is scoped to database/<username> and
# table/<username>/* via the `username` principal tag — THIS is the per-user
# isolation gate: a session tagged username=alice can only address database/alice.
# Athena is workgroup-scoped (ListQueryExecutions omitted — it would leak other
# users' queries); LF GetDataAccess lets the engine vend creds for the registered
# location; results read/write is the caller's own athenaresults/ prefix with an
# explicit Deny on DeleteObject (results can't be deleted or moved out). Athena
# also needs bucket-level s3:GetBucketLocation to verify the per-query output
# location (without it: "Unable to verify/create output bucket") — granted on the
# bucket itself, which leaks only the region, not data. The role is managed by
# module.data; analytics only adds this policy (module-level depends_on =
# [module.data] guarantees the role exists first).
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
