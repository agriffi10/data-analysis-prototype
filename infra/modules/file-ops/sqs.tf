# ── Request Queue + DLQ ────────────────────────────────────
# MessageGroupId is a SHA-256 HASH of "{bucket}/{sourceSpaceRoot}", NEVER the raw path: SQS
# caps a group id at 128 characters and an S3 key reaches 1024.
#
# ⚠ ORDERED DELIVERY IS NOT SERIALIZED EXECUTION, and here that distinction is the difference
# between working and losing data — a delete removing objects a concurrent move has already
# relocated is silent, unrecoverable loss with versioning off. THE SERIALIZATION IS THE
# PER-SPACE LOCK; this group id buys ordering and throughput isolation and nothing else.
#
# content_based_deduplication is OFF. Its OWN queue and its OWN DLQ, registered with the drain
# sweep, which names the feature by the DLQ — a dead-lettered file operation must never be
# reported as a file send. README.md.

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
