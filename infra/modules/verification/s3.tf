// SPEC-186 FR-004 — the archive plane's audit record.
//
// Two owed live assertions could not be made by ANY principal. SPEC-170's is the load-bearing
// one: that a `destination_occupied` refusal did NOT already initiate retrieval. Making it
// requires knowing whether `RestoreObject` was ever called for a run — and `dat-prod-archive`
// explicit-denies the laptop IAM user, its execution role trusts `lambda.amazonaws.com` only,
// the deploy role is GitHub-OIDC-only, and NO CLOUDTRAIL TRAILS EXIST. The script itself
// records that a refusal which had already started retrieval "looks identical from the UI", so
// there is no proxy, and the cost of being wrong is 3-5 billed, uncancellable hours.
//
// This is the read-only, audit-shaped answer the spec asked for rather than a grant on the
// data path: it answers "was RestoreObject called for this run" DIRECTLY, and it is the record
// a plane that spends real money on an uncancellable operation arguably should have had from
// the start.

resource "aws_s3_bucket" "trail" {
  bucket = var.trail_bucket_name
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket = aws_s3_bucket.trail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "trail" {
  bucket = aws_s3_bucket.trail.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

// Unfiltered and bucket-wide, like the archive vault's own expiry and for the same reason: a
// lifecycle rule can include a prefix but never exclude one, so a rule that missed a prefix
// would keep those objects forever without saying so.
resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id

  rule {
    id     = "expire-trail-objects"
    status = "Enabled"

    filter {}

    expiration {
      days = var.trail_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

// CloudTrail's own delivery grants, and NOTHING ELSE. Unlike the archive vault this bucket
// carries no allowlist: it is meant to be readable by an account principal with the ordinary
// read permissions an admin has, because a record nobody can read is the situation this whole
// requirement exists to fix. What it must not become is writable by anything but CloudTrail.
resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.trail.arn
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:aws:cloudtrail:${var.aws_region}:${var.account_id}:trail/${var.project_name}-${var.environment}-archive-audit"
          }
        }
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.trail.arn}/AWSLogs/${var.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = "arn:aws:cloudtrail:${var.aws_region}:${var.account_id}:trail/${var.project_name}-${var.environment}-archive-audit"
          }
        }
      }
    ]
    // NO blanket write-Deny here, and the omission is deliberate. The obvious one —
    // `Deny s3:PutObject` where `aws:PrincipalServiceName != cloudtrail.amazonaws.com` — rests
    // on a condition key CloudTrail's own delivery must populate for the Allow above to
    // survive it. If it does not, delivery fails and the trail is silently EMPTY, which is
    // this spec's own "did not run is never clean" failure with the evidence rather than a
    // scanner. The bucket is private, public access is blocked, and this policy grants
    // nothing but CloudTrail; the residual is that an account principal with identity-based
    // S3 write could tamper with the record, which is acceptable for an operator's
    // verification aid and would not be for a compliance vault.
  })
}
