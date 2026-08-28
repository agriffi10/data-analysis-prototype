// `RestoreObject` is an S3 OBJECT-level call, so CloudTrail classifies it as a DATA event and
// it never appears in the console's Event history. Data events for ONE bucket, management
// events for none. README.md.
resource "aws_cloudtrail" "archive_audit" {
  name           = "${var.project_name}-${var.environment}-archive-audit"
  s3_bucket_name = aws_s3_bucket.trail.id

  // Single-region and single-account: a multi-region trail would record calls this exists to
  // have no opinion about.
  is_multi_region_trail         = false
  include_global_service_events = false
  enable_log_file_validation    = true

  advanced_event_selector {
    name = "Object-level calls on the archive vault"

    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }

    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }

    // The ARN PREFIX form — which is why this module takes a bucket NAME, not an ARN.
    field_selector {
      field       = "resources.ARN"
      starts_with = ["arn:aws:s3:::${var.archive_bucket_name}/"]
    }
  }

  // CloudTrail checks the bucket policy at creation. Tofu cannot infer this ordering.
  depends_on = [aws_s3_bucket_policy.trail]
}
