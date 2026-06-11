# ── User-Space Bucket (Bucket 1) ─────────────────────────────────────────────
# Holds every user's files under their own username prefix ({username}/...) plus
# their future .config/connections.json. Private; per-user isolation is enforced
# by IAM principal tags on the shared portal role (SPEC-011/013), not by anything
# in this module.
#
# This module is storage only — the bucket and its hygiene config. The portal
# role, its prefix-scoped permission policy, and the bucket policy restricting
# access to that role all arrive in SPEC-011/013.

resource "aws_s3_bucket" "user_space" {
  bucket = var.user_space_bucket_name
}

# Block all public access — all four settings on.
resource "aws_s3_bucket_public_access_block" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Default server-side encryption with SSE-S3 (AES256).
resource "aws_s3_bucket_server_side_encryption_configuration" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Disable ACLs entirely — the bucket owner owns every object (BucketOwnerEnforced).
resource "aws_s3_bucket_ownership_controls" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning is intentionally OFF for the MVP — no version history or undo. This
# is a deliberate decision: overwrites and deletes are irreversible and the app
# guards them in the UI (see docs/architecture.md Known Constraints). Revisit if
# undo/version history is ever required. Lifecycle rules are also deferred until
# a spec needs them (SPEC-020 adds the first, for incomplete multipart uploads).
resource "aws_s3_bucket_versioning" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  versioning_configuration {
    status = "Disabled"
  }
}

# CORS — without this, browser SDK calls fail (matches docs/architecture.md).
# Origins always include local dev; the deployed app URL is added once known.
resource "aws_s3_bucket_cors_configuration" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  cors_rule {
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = var.app_url != "" ? ["http://localhost:5173", var.app_url] : ["http://localhost:5173"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]
    max_age_seconds = 3000
  }
}

# No bucket policy yet — SPEC-013 adds the policy restricting access to the portal
# role (and break-glass account root) once that role exists.
