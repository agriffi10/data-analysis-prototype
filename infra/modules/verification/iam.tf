// The read-only role a live check assumes: catalog read-back, the trail objects, and the trail's
// own status. NO write action appears anywhere in it, and a test asserts that.
//
// ⚠ THE PRINCIPAL ARNs COME FROM THE `TF_VAR_verification_principal_arns` REPO VARIABLE, NEVER A
// LOCAL terraform.tfvars. A local apply plans to DESTROY the data buckets, because no human
// identity here is on their policy allowlists and tofu reads them as absent. README.md.
//
// Empty by default, and the role is then NOT created. Delegating to the account root instead was
// rejected by the plan scan (CKV_AWS_61) for the right reason. The TRAIL is unconditional.
resource "aws_iam_role" "verification" {
  count = length(var.verification_principal_arns) > 0 ? 1 : 0

  name        = "${var.project_name}-${var.environment}-verification"
  description = "Read-only catalog and archive-audit access for live checks. No write action, and no grant on any data bucket."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = var.verification_principal_arns }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

// THREE GLUE ARNs, NOT `catalog` + `catalog/*` — Glue has no `catalog/*` hierarchy, and that
// form applies cleanly then DENIES AT RUNTIME. A test asserts the resource set.
//
// Deliberately NO `lakeformation:GetDataAccess`: it is the credential vend for a table's DATA,
// it is easy to add "to make GetTable work", and it is not needed for it.
//
// NO COMMENTS IN THE .tftpl — an IAM document must be printable ASCII, and comment keys with em
// dashes were rejected at CreatePolicy, invisible to validate and to the plan. README.md.
resource "aws_iam_role_policy" "verification" {
  count = length(aws_iam_role.verification)

  name = "${var.project_name}-${var.environment}-verification-permissions"
  role = aws_iam_role.verification[0].id

  policy = templatefile("${path.module}/policies/verification-role.json.tftpl", {
    aws_region       = var.aws_region
    account_id       = var.account_id
    trail_bucket_arn = aws_s3_bucket.trail.arn
    trail_arn        = aws_cloudtrail.archive_audit.arn
  })
}

// The IAM grant above is necessary and NOT SUFFICIENT — Lake Formation gates the catalog
// independently. The LF half is granted in modules/analytics, which owns the tag it hangs off.
// DESCRIBE alone, and no DATA_LOCATION_ACCESS. README.md.
