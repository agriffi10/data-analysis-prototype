// The archive plane's audit record: the only way to assert that a `destination_occupied`
// refusal did NOT already initiate retrieval. No principal in the account could make that
// assertion before this trail existed, there is no proxy for it, and the cost of being wrong is
// 3-5 billed, uncancellable hours. README.md.

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

// Unfiltered and bucket-wide: a lifecycle rule can INCLUDE a prefix but never EXCLUDE one, so
// a rule that missed one would keep those objects forever without saying so.
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

// CloudTrail's own delivery grants, and NOTHING ELSE. Deliberately readable by an ordinary
// admin — a record nobody can read is the situation this exists to fix. README.md.
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
    // NO blanket write-Deny, deliberately: the obvious one rests on a condition key
    // CloudTrail's delivery must populate for the Allow to survive it. If it does not,
    // delivery fails and the trail is SILENTLY EMPTY. README.md.
  })
}
