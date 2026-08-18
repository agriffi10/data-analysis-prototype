# ── The archive bucket ─────────────────────────────────────
# Bucket 5, holding nothing but archived objects at the GLACIER storage class, reachable
# by nothing but this control plane.
#
# THE BROWSER HAS NO RELATIONSHIP WITH THIS BUCKET AT ALL, and that is the design rather
# than an omission: there is NO CORS configuration below (the same explicit absence the
# admin bucket carries), the host is NOT in the CSP connect-src (modules/app —
# a reviewer must be able to read that enumerated list and see no archive host), and the
# portal role holds ZERO statements naming this ARN. The only route to archived bytes is
# a restore request through this plane, which is the whole point of archiving being
# reversible only through a request that takes hours.
#
# Hygiene mirrors the other four buckets (data/s3.tf, analytics/s3.tf): all public access
# blocked, SSE-S3, BucketOwnerEnforced, versioning off.

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

# Versioning OFF, matching every other bucket in this project (deferred by decision,
# 2026-08-03). It is worth saying explicitly here because the obvious next thought on an
# archive bucket is S3 Object Lock — which REQUIRES versioning, and which is out of
# scope for a second, independent reason: in compliance mode nothing can delete an
# object, not even root, so the cleanup of a restored archive would be impossible.
resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id

  versioning_configuration {
    status = "Disabled"
  }
}

# ── Retention is a CEILING, not a WORM floor (FR-001) ────────────────────────
# Every object expires 7 years after creation. Nothing here prevents an earlier delete —
# the restore deletes the archived copy once it has been put back, and it must be
# able to.
#
# THE EXPIRY RULE IS DELIBERATELY BUCKET-WIDE WITH NO PREFIX FILTER, and it is the exact
# INVERSE of the admin bucket's `admin_lifecycle_rules_are_prefix_scoped` check. That
# check exists because THAT bucket mixes `logs/` (retained forever) with expiring
# content, so an unfiltered expiring rule there would silently delete the logs. This
# bucket holds exactly one class of object, so the risk runs the other way: a prefix
# filter would be a silent way to leave some archived data unexpired past the retention
# the feature promises.
#
# S3 LIFECYCLE CAN INCLUDE A PREFIX BUT NEVER EXCLUDE ONE. So if a second content class
# is ever put in this bucket, the repair is NOT to add a filter here — that would leave
# the new class unexpired and this rule looking correct. It is to revisit this rule, and
# probably to give the new class its own bucket.
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

  # Bucket-wide and unfiltered (CKV_AWS_300), the disposition every other bucket already
  # carries. An abandoned multipart upload leaves orphaned parts that are billed and
  # invisible to every listing. It carries no `expiration` and can only discard the PARTS
  # of an upload that never completed, so it cannot delete an object.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ── Bucket policy: this plane and the deploy role, nobody else (FR-001) ──────
# The same `StringNotLike aws:PrincipalArn` shape the user-space bucket policy uses. It
# is what makes "the browser has no relationship with this bucket" enforced rather than
# merely true today: an identity policy that grew a statement naming this ARN would still
# be denied here.
#
# The deploy role is excluded for the recorded reason: without it the deploy role cannot
# HeadBucket, `tofu refresh` reads the bucket as deleted, and every plan proposes a
# destructive recreate.
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
