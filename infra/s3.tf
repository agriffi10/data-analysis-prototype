data "aws_caller_identity" "current" {}

# ── Static Assets Bucket ─────────────────────────────────────────────────────
# Private bucket for the built SPA. Only accessible via CloudFront OAC — not public.

resource "aws_s3_bucket" "static_assets" {
  bucket = "${var.project_name}-static-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Grants CloudFront OAC read access; denies all other principals.
# Must be applied after the CloudFront distribution exists (references its ARN).
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
