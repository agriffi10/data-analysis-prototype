# ── Lake Formation registration of the shared bucket (SPEC-056 FR-003) ───────
# Register dat-prod-shared-space as an LF location in HYBRID mode (as the user-space
# bucket, SPEC-032) so the file browser keeps direct-IAM S3 (SPEC-057) while Athena
# reads shared tables via LF. LF assumes a custom registration role (below) to vend
# temporary S3 creds for the location; the role is scoped to the shared bucket only.
#
# The LF data-lake-settings singleton (admins + IAMAllowedPrincipals removal) lives
# in the analytics module and is already applied account-wide (SPEC-032); the
# orchestrator role is added to its admins list there (SPEC-056, root-wired). This
# file only adds the per-bucket registration, which is independent of those settings.
# Per-shared-DB LF grants + the DATA_LOCATION_ACCESS grant on this location are issued
# by the orchestrator (now an LF admin) at create time (SPEC-051+).

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

# WARNING: hybrid mode — do NOT flip to enforced without opting in EVERY principal
# first, or the file browser's direct S3 access to the shared bucket breaks.
resource "aws_lakeformation_resource" "shared_space" {
  arn                   = aws_s3_bucket.shared_space.arn
  role_arn              = aws_iam_role.lf_registration.arn
  hybrid_access_enabled = true

  depends_on = [aws_iam_role_policy.lf_registration]
}
