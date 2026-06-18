# ── Lake Formation registration role (SPEC-032 FR-005) ───────────────────────
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

# ── Lake Formation admin role for the account root user ──────────────────────
# A human-assumable role that carries Lake Formation admin authority, so the
# account owner can inspect/manage the catalog (the deploy role + provisioner
# Lambda are the only other LF admins, and neither is human-assumable). LF admin
# is a separate model from IAM, so even the root user can't see per-user databases
# without this. Trust is restricted to the LITERAL root user (Principal = account +
# a PrincipalArn == :root condition), so no IAM user/role can assume it — only root,
# via "Switch role" in the console. The ARN is also constructed (below) and added to
# the LF admins list as a KNOWN-at-plan string (an unknown role ARN inside the LF
# admins compact() silently drops the change — see lakeformation.tf).
locals {
  lf_admin_role_name = "${var.project_name}-analytics-lf-admin-role"
  lf_admin_role_arn  = "arn:aws:iam::${var.account_id}:role/${local.lf_admin_role_name}"
}

resource "aws_iam_role" "lf_admin" {
  name = local.lf_admin_role_name
  assume_role_policy = templatefile("${path.module}/policies/lf-admin-trust.json.tftpl", {
    account_id = var.account_id
  })

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_iam_role_policy" "lf_admin" {
  name = "lf-and-glue-admin"
  role = aws_iam_role.lf_admin.id

  policy = templatefile("${path.module}/policies/lf-admin-permissions.json.tftpl", {
    aws_region = var.aws_region
    account_id = var.account_id
  })
}

# ── Portal role — analytics permissions (SPEC-032 FR-006) ────────────────────
# A SECOND inline policy on the shared portal role (the first, "user-space-access",
# is attached by module.data / SPEC-013). Glue is scoped to database/<username> and
# table/<username>/* via the `username` principal tag — THIS is the per-user
# isolation gate: a session tagged username=alice can only address database/alice.
# Athena is workgroup-scoped (ListQueryExecutions omitted — it would leak other
# users' queries); LF GetDataAccess lets the engine vend creds for the registered
# location; results read/write is the caller's own athenaresults/ prefix with an
# explicit Deny on DeleteObject (results can't be deleted or moved out). The role
# is managed by module.data; analytics only adds this policy (module-level
# depends_on = [module.data] guarantees the role exists first).
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
