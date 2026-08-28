# ── Lake Formation registration of the shared bucket ───────
# Registered in HYBRID mode so the file browser keeps direct-IAM S3 while Athena reads shared
# tables via LF. LF assumes a registration role scoped to this bucket only.
#
# The LF data-lake-settings singleton lives in modules/analytics and is applied account-wide;
# this file only adds the per-bucket registration. README.md.

resource "aws_iam_role" "lf_registration" {
  name               = "${var.project_name}-${var.environment}-shared-space-lf-registration-role"
  assume_role_policy = templatefile("${path.module}/policies/lf-registration-trust.json.tftpl", {})

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_iam_role_policy" "lf_registration" {
  name = "s3-location-access"
  role = aws_iam_role.lf_registration.id

  policy = templatefile("${path.module}/policies/lf-registration-permissions.json.tftpl", {
    bucket_arn = aws_s3_bucket.shared_space.arn
  })
}

# ⚠ HYBRID MODE — do NOT flip to enforced without opting in EVERY principal first, or the file
# browser's direct S3 access to this bucket breaks.
resource "aws_lakeformation_resource" "shared_space" {
  arn                   = aws_s3_bucket.shared_space.arn
  role_arn              = aws_iam_role.lf_registration.arn
  hybrid_access_enabled = true

  depends_on = [aws_iam_role_policy.lf_registration]
}

# One location-level grant so members can CREATE tables / CTAS over the shared bucket.
# Per-space isolation is still IAM (the membership-tag scoping), not this grant.
resource "aws_lakeformation_permissions" "portal_shared_location" {
  principal   = local.portal_role_arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = aws_s3_bucket.shared_space.arn
  }

  depends_on = [aws_lakeformation_resource.shared_space]
}

# THE LOCATION HALF THE `portal-managed` LF-TAG CANNOT EXPRESS — tags cover DB and table
# resources, NOT S3 locations. One per-bucket grant per control-plane execution role; per-space
# gating stays at validate-authorize. An empty list (standalone plan) means no grants.
resource "aws_lakeformation_permissions" "control_plane_shared_location" {
  for_each    = toset(compact(var.control_plane_execution_role_arns))
  principal   = each.value
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = aws_s3_bucket.shared_space.arn
  }

  depends_on = [aws_lakeformation_resource.shared_space]
}
