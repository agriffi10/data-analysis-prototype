# ── Request Queue + DLQ ────────────────────────────────────
# MessageGroupId is a SHA-256 HASH of "{bucket}/{sourceSpaceRoot}", NEVER the raw path: SQS
# caps a group id at 128 characters and an S3 key reaches 1024, so the raw form is a length
# failure that only appears for deeply-nested sources.
#
# content_based_deduplication is OFF: two byte-identical sends a user genuinely repeats must
# not be absorbed by a 5-minute window.
#
# ITS OWN QUEUE AND ITS OWN DLQ — the drain sweep it is registered with names the feature by
# the DLQ, so a dead-lettered send must never be reported as a share. README.md.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = false
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
