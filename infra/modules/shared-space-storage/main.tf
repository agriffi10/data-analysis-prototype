# ── Shared-Space Bucket (Bucket 2) ──────────────────────────
# Objects live under {name}/... and are seen by ALL members of that space — a single shared
# copy, not per-user copies. Hygiene mirrors the user-space bucket.
#
# THIS BUCKET HAS NO BUCKET POLICY, which is why a control-plane role missing from the
# USER-SPACE bucket's allowlist half-works: every shared-space path succeeds and every personal
# one fails. See modules/data and ../../planes/shared-spaces/README.md.

# IAM propagation guard. 60s, not 30s — the Lambda and IAM role creates this module makes
# still race at 30s.
#
# ⚠ EVERY resource needing a freshly-granted permission depends on it — the bucket here, and the
# plane and the transfer reader through their root calls' depends_on on this module.
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

# Without this every presigned GET and PUT the browser redeems fails preflight. Origins are
# ADDITIVE.
resource "aws_s3_bucket_cors_configuration" "shared_space" {
  bucket = aws_s3_bucket.shared_space.id

  cors_rule {
    allowed_methods = ["GET", "PUT"]
    # `localhost` stays, and NOT because of the dev-unauth path: a developer running `npm run dev`
    # against a deployed API still redeems presigned URLs from it.
    #
    # ONE ORIGIN NOW. The CloudFront entry was the rollback and went with the distribution.
    #
    # GET AND PUT ARE THE WHOLE PRESIGNED SURFACE the browser redeems: a presigned GET to
    # download, and a presigned PUT to upload over XMLHttpRequest. HEAD (objectExists,
    # getObjectMetadata, every collision pre-check), DELETE and multipart POST were the
    # browser's own SDK calls and are API routes now. A stale-but-working CORS rule is
    # invisible, so their absence is asserted rather than assumed.
    #
    # `allowed_headers` and `max_age_seconds` are deliberately UNCHANGED: the header set a
    # presigned PUT carries depends on what the signer signed, and a missing entry fails the
    # PREFLIGHT, which the browser reports as a generic network error naming nothing.
    allowed_origins = compact(["http://localhost:5173", var.spa_origin])
    allowed_headers = ["*"]
    # ETag alone. The other three were removed against a grep over apps/portal/src returning
    # ZERO readers of each — a named absent reader, not tidiness. ETag is kept WITHOUT such a
    # grep and deliberately: an exposed header nobody reads costs nothing, while a missing one
    # fails as an opaque browser error at the first upload.
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}
