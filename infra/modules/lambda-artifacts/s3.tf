# ── Lambda Deployment Artifacts Bucket (SPEC-012) ────────────────────────────
# Staging bucket for Lambda code packages. GitHub Actions
# (.github/workflows/deploy-lambdas.yml) builds each function's zip, uploads it
# here under {function}/{git-sha}.zip, then calls update-function-code referencing
# the object. Shared by every Lambda under /lambdas. Private — no public access,
# no browser CORS (only the deploy role and the Lambda service read it).

# IAM propagation guard. The module-level `depends_on = [module.base]` orders the
# API calls so the deploy-role policy (which grants this bucket's management) is
# written before this module runs — but IAM is eventually consistent, so the
# deploy role using that grant to create the bucket in the same apply can race
# the propagation and hit a transient AccessDenied. This pause closes that window.
resource "time_sleep" "wait_for_deploy_policy" {
  create_duration = "30s"
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

# Artifacts are disposable: Lambda copies the code internally on
# update-function-code, so an expired S3 object never affects a running function.
# Expire old packages after 30 days to keep the bucket bounded.
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
}
