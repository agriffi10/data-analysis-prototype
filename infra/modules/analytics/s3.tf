# ── Admin-Only Athena Results Bucket (SPEC-032 FR-003) ───────────────────────
# The Athena workgroup's default/fallback output location and a future admin/audit
# store. NO end-user access: the portal role is never granted anything on this
# bucket (FR-006 grants the role only the user-space {username}/athenaresults/
# prefix). Reserved for future admin/audit roles, which are out of scope here.
#
# User-facing query results and history do NOT live here — they go to
# {username}/athenaresults/ in the user-space bucket (SPEC-010), readable by the
# user and delete-protected (FR-006). This bucket only ever receives a write when a
# query omits an explicit OutputLocation (it shouldn't), keeping that data out of
# any user-readable location.
#
# Hygiene mirrors the user-space bucket (data/s3.tf): all public access blocked,
# SSE-S3, BucketOwnerEnforced, versioning off (MVP). Created by the deploy role,
# which holds s3:* on this ARN (modules/base S3AthenaAdminBucketManage, FR-007);
# the time_sleep guard in athena.tf covers both this bucket and the workgroup.

resource "aws_s3_bucket" "athena_admin" {
  bucket = var.athena_admin_bucket_name

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_s3_bucket_public_access_block" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning OFF for the MVP (matches the user-space bucket).
resource "aws_s3_bucket_versioning" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Expire admin/fallback output after the retention window. (The user-facing
# athenaresults/ prefix in the user-space bucket has NO expiry — kept indefinitely
# per the SPEC-032 Open Questions decision; this lifecycle applies only here.)
resource "aws_s3_bucket_lifecycle_configuration" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  rule {
    id     = "expire-admin-results"
    status = "Enabled"

    filter {}

    expiration {
      days = var.admin_results_retention_days
    }
  }
}

# No CORS: this bucket is never read by the browser. User-facing result downloads
# read from the user-space {username}/athenaresults/ prefix instead (SPEC-034).
