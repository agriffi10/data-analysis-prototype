# ── Request Queue + DLQ ────────────────────────────────────
# FIFO with a SINGLE CONSTANT MessageGroupId, so requests are processed strictly one-at-a-time.
#
# DUPLICATE-NAME SAFETY DOES NOT DEPEND ON SQS CONTENT DEDUP — that only collapses
# byte-identical bodies inside a 5-minute window. THE REGISTRY'S CONDITIONAL PUT
# (If-None-Match) IS THE REAL GUARD, and serial intake is what makes it sufficient. README.md.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = 3
  })

  depends_on = [time_sleep.wait_for_deploy_policy]
}
