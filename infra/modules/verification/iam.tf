// SPEC-186 FR-004 AC3 — a named principal that can read the catalog back, and nothing else.
//
// SPEC-149's `Description`/column-comment preservation check and SPEC-153's owed foreign
// projection fixture both fail today with `Insufficient Lake Formation permission(s): Required
// Describe`, from every principal a human has. The role below closes that with a READ-ONLY
// grant that touches no data bucket: `glue:GetTable`/`GetTableVersions` on the catalog, the
// trail objects, and the trail's own status. No write action appears anywhere in it, and a
// test asserts that.
//
// TRUSTED TO THE ACCOUNT ROOT, not to a hardcoded IAM user. Delegating to the account is the
// standard idiom and it means the role does not have to be re-applied whenever the operator's
// own principal changes — an account principal still needs its own `sts:AssumeRole` on this
// role, so the delegation grants nothing by itself. An external id is not used: there is no
// third party here, and a shared secret in state would be worse than the account boundary.
resource "aws_iam_role" "verification" {
  name        = "${var.project_name}-${var.environment}-verification"
  description = "SPEC-186 FR-004: read-only catalog and archive-audit access for live checks. No write action, and no grant on any data bucket."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "verification" {
  name = "${var.project_name}-${var.environment}-verification-permissions"
  role = aws_iam_role.verification.id

  policy = templatefile("${path.module}/policies/verification-role.json.tftpl", {
    glue_catalog_arn = var.glue_catalog_arn
    trail_bucket_arn = aws_s3_bucket.trail.arn
    trail_arn        = aws_cloudtrail.archive_audit.arn
  })
}

// The IAM grant above is necessary and NOT sufficient: Lake Formation gates the catalog
// independently, and its refusal — `Insufficient Lake Formation permission(s): Required
// Describe` — is the exact error the owed read-backs hit.
//
// The LF half is granted in `modules/analytics`, NOT here, because it hangs off the
// `portal-managed` LF-Tag that module owns (SPEC-070/111): the databases are created at
// runtime, one per username and one per shared space, so nothing static can enumerate them and
// a tag policy is the only expression that covers them all. This module outputs the role ARN
// and analytics grants DESCRIBE against it — deliberately DESCRIBE alone, and deliberately no
// `DATA_LOCATION_ACCESS`, so the role can read a table's definition and still not read a byte
// of what the table points at.
