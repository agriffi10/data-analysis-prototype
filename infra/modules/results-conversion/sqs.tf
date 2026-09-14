# ── Request Queue + DLQ ────────────────────────────────────
# MessageGroupId is the actor's USERNAME, so one user's conversions are delivered in order
# while different users run in parallel. MessageDeduplicationId is the request id, so a browser
# retry of one submit is one execution — content_based_deduplication is OFF on both queues.
#
# Its OWN queue and its OWN DLQ, registered with the drain sweep, which names the feature by
# the DLQ — a dead-lettered conversion must never be reported as a file operation.

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
