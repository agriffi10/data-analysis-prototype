// SPEC-186 FR-004 AC1. `RestoreObject` is an S3 OBJECT-level call, which CloudTrail classifies
// as a DATA event — it never appears in the console's Event history, which is why nothing today
// records it. The trail below records data events for ONE bucket and management events for
// none, so it is neither a general-purpose audit trail nor a cost of any size.
//
// KEYED SO ONE RUN CAN BE ISOLATED, which AC1 requires: the archive key layout is
// `{personal|shared}/{space}/{archiveId}/…` (SPEC-168), so `requestParameters.key` in each
// record carries the archive id, and a live check greps for the id it was handed. No extra
// correlation field is needed — and none could be added, since the caller is a Lambda whose
// request the plane does not tag.
resource "aws_cloudtrail" "archive_audit" {
  name           = "${var.project_name}-${var.environment}-archive-audit"
  s3_bucket_name = aws_s3_bucket.trail.id

  // Single-region and single-account: the archive plane lives in one region, and a
  // multi-region trail would record calls this exists to have no opinion about.
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

    // The ARN PREFIX form, which is why this takes a bucket NAME rather than an ARN: it must
    // match every object under the bucket, and `starts_with` on the object ARN is how S3 data
    // events are scoped to one bucket.
    field_selector {
      field       = "resources.ARN"
      starts_with = ["arn:aws:s3:::${var.archive_bucket_name}/"]
    }
  }

  // The bucket policy is what CloudTrail checks at creation, so the trail cannot be created
  // before it exists — an ordering AWS enforces and Tofu cannot infer from these references.
  depends_on = [aws_s3_bucket_policy.trail]
}
