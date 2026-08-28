# ── Request Queue + DLQ ────────────────────────────────────
# MessageGroupId is the SOURCE database.table, so repeated shares of one source serialize and
# a heavy copy never overlaps itself.
#
# content_based_deduplication is OFF here, unlike the table-builder queue: two byte-identical
# share requests a user GENUINELY repeats (a re-share after deleting the copy) must not be
# silently absorbed by a 5-minute window. The explicit MessageDeduplicationId is the guard.

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
