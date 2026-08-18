# ── Shared-Space Bucket (Bucket 2) ──────────────────────────
# Backs every shared connection: objects live under {name}/... and are seen by all
# members of that space (a single shared copy, not per-user copies). Hygiene mirrors
# the user-space bucket (data/s3.tf): all public access blocked, SSE-S3,
# BucketOwnerEnforced, versioning off (MVP), abort-incomplete-multipart lifecycle.
#
# Is plumbing only — this bucket is created with NO access grants and NO
# bucket policy. The membership-tag portal-role statements, the shared-results
# delete-denies, and the Lake Formation hybrid registration all arrive in SPEC-056;
# the per-space provisioning (prefix marker, Glue DB) in SPEC-051+.

# IAM propagation guard — same rationale as data/s3.tf and auth/lambda.tf. The
# module-level depends_on = [module.base] orders the deploy-role policy (which now
# grants s3 / sqs / pipes / states / lambda / iam / logs for this module) before
# this module runs, but IAM is eventually consistent; this pause absorbs the
# propagation window so the deploy role's first create call in the same apply
# doesn't race the grant and hit AccessDenied. 60s (not 30s) because the
# lambda/iam-role creates this module makes still race at 30s (auth/lambda.tf).
# EVERY resource that needs a freshly-granted permission depends on it — the bucket,
# the queues, the IAM roles, the log groups, the function, the state machine, the
# pipe — not just the bucket, or those calls race the propagation.
resource "time_sleep" "wait_for_deploy_policy" {
  create_duration = "60s"
}

resource "aws_s3_bucket" "shared_space" {
  bucket = var.shared_space_bucket_name

  depends_on = [time_sleep.wait_for_deploy_policy]
}

# Block all public access — all four settings on.
resource "aws_s3_bucket_public_access_block" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Default server-side encryption with SSE-S3 (AES256).
resource "aws_s3_bucket_server_side_encryption_configuration" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Disable ACLs entirely — the bucket owner owns every object (BucketOwnerEnforced).
resource "aws_s3_bucket_ownership_controls" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning OFF for the MVP (matches the user-space and admin buckets).
resource "aws_s3_bucket_versioning" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Lifecycle — abort incomplete multipart uploads after 7 days (mirrors SPEC-016).
# Shared-space uploads use the same managed lib-storage multipart path as the
# user-space bucket; a browser killed mid-upload leaves billable, invisible parts.
resource "aws_s3_bucket_lifecycle_configuration" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CORS — without this, browser SDK calls fail (matches data/s3.tf). Origins always
# include local dev; the deployed app URL is added once known.
resource "aws_s3_bucket_cors_configuration" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  cors_rule {
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = var.app_url != "" ? ["http://localhost:5173", var.app_url] : ["http://localhost:5173"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]
    max_age_seconds = 3000
  }
}
