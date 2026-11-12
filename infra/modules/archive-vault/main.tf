# ── The archive bucket ─────────────────────────────────────
# Bucket 5, holding nothing but archived objects at GLACIER.
#
# ⚠ THE BROWSER HAS NO RELATIONSHIP WITH THIS BUCKET AT ALL, and that is the design: NO CORS
# configuration below, the host is NOT in the CSP connect-src, the portal role holds ZERO
# statements naming this ARN, and the bucket policy denies everything but this plane. The only
# route to archived bytes is a restore through this plane. README.md.

resource "aws_s3_bucket" "archive" {
  bucket = var.archive_bucket_name
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket = aws_s3_bucket.archive.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning OFF, matching every other bucket. Worth stating HERE because the obvious next
# thought on an archive bucket is S3 OBJECT LOCK — which REQUIRES versioning, and is out of
# scope for a second reason: in compliance mode NOTHING can delete an object, not even root,
# so the cleanup of a restored archive would be impossible. README.md.
resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id

  versioning_configuration {
    status = "Disabled"
  }
}

# ── Retention is a CEILING, not a WORM floor ────────────────────────
# Nothing here prevents an earlier delete — the restore deletes the archived copy once it is
# back, and it must be able to.
#
# ⚠ THE EXPIRY RULE IS DELIBERATELY BUCKET-WIDE WITH NO PREFIX FILTER, the exact INVERSE of the
# admin bucket's prefix-scoped check: that bucket mixes retained and expiring content, this one
# holds a single class, so a filter here would silently leave data unexpired past the retention
# the feature promises.
#
# S3 LIFECYCLE CAN INCLUDE A PREFIX BUT NEVER EXCLUDE ONE, so if a second content class ever
# lands here THE REPAIR IS NOT TO ADD A FILTER — that leaves the new class unexpired and this
# rule looking correct. README.md.
resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id

  rule {
    id     = "expire-archived-objects"
    status = "Enabled"

    filter {}

    expiration {
      days = var.archive_retention_days
    }
  }

  # CKV_AWS_300. It carries no `expiration` and can only discard the PARTS of an upload that
  # never completed, so it cannot delete an object.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ── Bucket policy: this plane and the deploy role, nobody else ──────
# What makes "the browser has no relationship with this bucket" ENFORCED rather than merely
# true today — an identity policy that grew a statement naming this ARN would still be denied.
#
# The deploy role is excluded, or it cannot HeadBucket, `tofu refresh` reads the bucket as
# deleted, and every plan proposes a destructive recreate. README.md.
resource "aws_s3_bucket_policy" "archive" {
  bucket = aws_s3_bucket.archive.id

  policy = templatefile("${path.module}/policies/archive-bucket-policy.json.tftpl", {
    bucket_arn         = aws_s3_bucket.archive.arn
    execution_role_arn = var.execution_role_arn
    deploy_role_arn    = var.deploy_role_arn
    account_id         = var.account_id
  })

  depends_on = [aws_s3_bucket_public_access_block.archive]
}

# No CORS configuration, and the absence is the point. See the header.
