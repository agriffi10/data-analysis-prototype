# ── Lambda Deployment Artifacts Bucket ────────────────────────────
# Staging bucket for Lambda code packages. See README.md.

# IAM propagation guard: the deploy role can race its own grant's propagation and hit a
# transient AccessDenied. 60s, not 30s — a bucket-config call raced even after CreateBucket
# succeeded. README.md.
resource "time_sleep" "wait_for_deploy_policy" {
  create_duration = "60s"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = var.bucket_name

  depends_on = [time_sleep.wait_for_deploy_policy]
}

# Block all public access — all four settings on.
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Default server-side encryption with SSE-S3 (AES256).
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Disable ACLs entirely — the bucket owner owns every object (BucketOwnerEnforced).
resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Artifacts are disposable — Lambda copies the code internally on update-function-code, so an
# expired object never affects a running function.
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-old-artifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }

  # CKV_AWS_300. An interrupted runner is the ordinary way this bucket acquires orphaned
  # parts — billed, and invisible to every listing.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
