# Private: only the distribution reads it. Everything in it can be rebuilt from a commit and the
# module's own config.json, so a switch to the web tier can take it with its contents.
resource "aws_s3_bucket" "portal" {
  bucket        = "${var.project_name}-${var.environment}-portal-static"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "portal" {
  bucket = aws_s3_bucket.portal.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Nothing here expires objects: the deploy's own --delete pass owns that, and an expiry would race it.
resource "aws_s3_bucket_lifecycle_configuration" "portal" {
  bucket = aws_s3_bucket.portal.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "portal" {
  bucket = aws_s3_bucket.portal.id

  # After the access block: S3 can refuse a policy written while that is still being applied.
  depends_on = [aws_s3_bucket_public_access_block.portal]

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
        Resource = "${aws_s3_bucket.portal.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.portal.arn
          }
        }
      }
    ]
  })
}

# Terraform owns this object and the deploy's sync never touches it: the file is not in dist/, and
# the only --delete is scoped to assets/. A value changing is an apply, not a rebuild.
#
# `no-store` because a document cached from another environment renders a working portal pointed at
# the wrong account, and nothing on screen tells them apart.
resource "aws_s3_object" "runtime_config" {
  bucket        = aws_s3_bucket.portal.id
  key           = "config.json"
  content_type  = "application/json"
  cache_control = "no-store"
  content = jsonencode(merge(
    { version = 1 },
    { for key, value in var.runtime_config : key => value if value != "" },
  ))
}
