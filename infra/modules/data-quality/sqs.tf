# ── Request Queue + DLQ ────────────────────────────────────
# MessageGroupId is the SHA-256 HEX DIGEST of the canonical target location, NEVER the raw
# location: SQS caps a group id at 128 characters and S3 keys reach 1024. The other producers
# get away with raw ids only because they group by a bounded catalog identifier.
#
# content_based_deduplication is OFF, and turning it on would be ACTIVELY WRONG: a re-check of
# the same location with the same body is a legitimate re-run the user asked for. README.md.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                       = local.requests_queue_name
  fifo_queue                 = true
  visibility_timeout_seconds = 60
  sqs_managed_sse_enabled    = true

  # OFF by design. DO NOT turn this on — it collapses a deliberate re-check of an unchanged
  # location into a no-op inside the 5-minute window.
  content_based_deduplication = false

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
