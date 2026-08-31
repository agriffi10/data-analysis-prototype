# ── Static Assets Bucket ─────────────────────────────────────────────────────
# Private bucket for the built SPA. Only accessible via CloudFront OAC — not public.

resource "aws_s3_bucket" "static_assets" {
  bucket = var.static_bucket_name

  # Terraform cannot DeleteBucket a bucket holding objects, and this one holds a whole SPA
  # build. Without this the retirement's destroy fails PART WAY THROUGH, with the state
  # migrations and the deploy-role grant timing both mid-flight — the worst point in the
  # sequence to stop. Set here, one merge ahead of the destroy, where it changes nothing.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CKV_AWS_300, and the only lifecycle rule this bucket has or needs. NOTHING here expires
# objects — the deploy's own `--delete` pass owns reconciliation, and an expiry would race it.
resource "aws_s3_bucket_lifecycle_configuration" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOAC"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.static_assets.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.portal.arn
          }
        }
      }
    ]
  })
}
