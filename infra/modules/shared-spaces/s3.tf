# ── Shared-Space Bucket (Bucket 2) ──────────────────────────
# Objects live under {name}/... and are seen by ALL members of that space — a single shared
# copy, not per-user copies. Hygiene mirrors the user-space bucket.
#
# THIS BUCKET HAS NO BUCKET POLICY, which is why a control-plane role missing from the
# USER-SPACE bucket's allowlist half-works: every shared-space path succeeds and every personal
# one fails. See modules/data. README.md.

# IAM propagation guard. 60s, not 30s — the Lambda and IAM role creates this module makes
# still race at 30s.
#
# ⚠ EVERY resource needing a freshly-granted permission depends on it — the bucket, the queues,
# the roles, the log groups, the functions, the machine, the pipe — NOT JUST THE BUCKET.
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

# Versioning OFF, matching the other buckets. Overwrites and deletes are irreversible.
resource "aws_s3_bucket_versioning" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  versioning_configuration {
    status = "Disabled"
  }
}

# A browser killed mid-upload leaves billable, invisible parts.
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

# Without this every browser SDK call fails preflight. Origins are ADDITIVE.
resource "aws_s3_bucket_cors_configuration" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  cors_rule {
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    # `localhost` stays, and NOT because of the dev-unauth path: a developer running `npm run dev`
    # against a deployed API still redeems presigned URLs from it. `app_url` stays for the whole
    # arc — CloudFront is the rollback until it is retired, and removing it here would break the
    # rollback in exactly the way that is only discovered when it is needed. `allowed_methods` is
    # left alone for the same reason: the rollback is to the CURRENT bundle, which issues HEAD,
    # DELETE and multipart POST, so narrowing to GET/PUT would keep the origin allowlisted while
    # breaking every method it uses.
    allowed_origins = compact(["http://localhost:5173", var.app_url, var.spa_origin])
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]
    max_age_seconds = 3000
  }
}
