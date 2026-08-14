// SPEC-186 FR-004 AC3 — a named principal that can read the catalog back, and nothing else.
//
// SPEC-149's `Description`/column-comment preservation check and SPEC-153's owed foreign
// projection fixture both fail today with `Insufficient Lake Formation permission(s): Required
// Describe`, from every principal a human has. The role below closes that with a READ-ONLY
// grant that touches no data bucket: `glue:GetTable`/`GetTableVersions` on the catalog, the
// trail objects, and the trail's own status. No write action appears anywhere in it, and a
// test asserts that.
//
// TRUSTED TO NAMED PRINCIPALS, AND THE ROLE DOES NOT EXIST UNTIL ONE IS NAMED.
//
// The first version delegated to the account root (`arn:aws:iam::{account}:root`), which is the
// standard AWS idiom and grants nothing by itself — an account principal still needs its own
// `sts:AssumeRole`. **Checkov's plan scan rejected it (`CKV_AWS_61`), and rejecting it was
// right.** SPEC-139's rule for the accept list is that it holds findings with *no scopable
// alternative* — CloudFront and Cognito creation have no ARN before the resource exists, and no
// applicable condition key. That is not true here: naming the principal IS the alternative, so
// accepting the finding would have been suppressing a fixable one.
//
// `verification_principal_arns` is empty by default and the role is then **not created**, which
// is deliberate on two counts. The ARNs are operator identities that do not belong in git, so
// they are set in `terraform.tfvars` (gitignored) — and a role nobody has named is a role nobody
// needs. **The TRAIL is unconditional**: it is the half that unblocks SPEC-170's negative
// assertion, and it depends on no principal at all.
resource "aws_iam_role" "verification" {
  count = length(var.verification_principal_arns) > 0 ? 1 : 0

  name        = "${var.project_name}-${var.environment}-verification"
  description = "SPEC-186 FR-004: read-only catalog and archive-audit access for live checks. No write action, and no grant on any data bucket."

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

resource "aws_iam_role_policy" "verification" {
  count = length(aws_iam_role.verification)

  name = "${var.project_name}-${var.environment}-verification-permissions"
  role = aws_iam_role.verification[0].id

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
